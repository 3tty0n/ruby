import block as block_mod
import boot
import debug
import dispatch
import gcroots
import helpers
import insns
import optable
import rubycall
import symbols
import value
from error import RPyYarvError, RubyException, UnsupportedOperation
from frame import (Frame, PENDING_BREAK, PENDING_NEXT, PENDING_NONE,
                   PENDING_RAISE, PENDING_RETURN)
from iseq import CATCH_ENSURE, CATCH_RESCUE, NO_BLOCK_ISEQ
from rlib import (JitDriver, StackOverflow, always_inline, check_stack_overflow,
                  dont_look_inside, promote, unroll_safe)

TO_S = symbols.intern('to_s')
DUP = symbols.intern('dup')


def define_method(frame, mid, w_iseq):
    """A def in a class body lands on it; a toplevel def is private on Object."""
    klass = frame.cref
    if klass == 0:
        dispatch.define(value.core_class(value.C_OBJECT), mid, w_iseq, True)
    else:
        dispatch.define(klass, mid, w_iseq, False, klass)


@unroll_safe
def invoke(frame, w_ci, w_block=None):
    if w_ci.blockarg:
        # Above the arguments, and read before it is popped so the frame keeps
        # it marked while _block_from_value may allocate (vm_args.c:1119).
        top = frame.sp - 1
        if top < 0:
            raise UnsupportedOperation(
                "call to '%s' passes a &block the stack does not hold"
                % symbols.name_of(w_ci.mid))
        w_block = _block_from_value(frame, frame.stack[top])
        frame.pop()
    argc = w_ci.argc
    recv_at = frame.sp - argc - 1
    if recv_at < 0:
        raise UnsupportedOperation(
            "call to '%s' with %d argument(s) underflows the stack"
            % (symbols.name_of(w_ci.mid), argc))
    if not w_ci.simple:
        raise UnsupportedOperation(
            "call to '%s' passes arguments RPyYARV does not support"
            % symbols.name_of(w_ci.mid))

    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    # Promoted: the guard on the class word is the inline cache, and the
    # lookup below folds away behind it.
    klass = promote(value.class_of(recv))
    entry = dispatch.lookup(klass, w_ci.mid)
    callee_iseq = None
    if entry is not None and (w_ci.fcall or not entry.private):
        if entry.kind != dispatch.KIND_ISEQ:
            return _attr_send(frame, entry, recv, recv_at, argc)
        callee_iseq = entry.w_iseq

    if callee_iseq is not None:
        if w_block is None or w_ci.blockarg:
            # A break unwinds to the send the block was *written* at, not to
            # one that only passed it on, so only that send catches it.
            return _enter(frame, entry, recv, recv_at, argc, w_ci.mid, w_block)
        try:
            return _enter(frame, entry, recv, recv_at, argc, w_ci.mid,
                          w_block)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value

    if entry is None and argc == 1 and _is_identity_mid(w_ci.mid) \
            and helpers.identity_op(recv, w_ci.mid):
        same = recv == frame.stack[recv_at + 1]
        if w_ci.mid == helpers.NEQ:
            same = not same
        _drop(frame, recv_at)
        debug.count_native()
        return value.newbool(same)
    if _is_attr_mid(w_ci.mid) and argc > 0 \
            and not value.is_immediate(recv) and dispatch.is_known_class(recv):
        return _define_attrs(frame, w_ci, recv, recv_at, argc)
    if w_ci.mid == BLOCK_GIVEN and w_ci.fcall and argc == 0:
        # rb_f_block_given_p reads the *caller's* frame (vm.c:1862); out
        # through rb_funcallv it would find a CRuby frame instead.
        _drop(frame, recv_at)
        return value.newbool(frame.block is not None)
    if w_block is not None and w_ci.mid == NEW \
            and dispatch.is_known_class(recv):
        entry = dispatch.lookup(promote(recv), INITIALIZE)
        if entry is not None and entry.kind == dispatch.KIND_ISEQ:
            return _new_with_block(frame, entry, recv, recv_at, argc, w_block)
    if proxy.value != 0 and recv == proxy.value:
        return _block_send(frame, w_ci, recv_at, argc, frame.block)
    if len(blocks.by_proc) > 0 and _is_proxy_call(w_ci.mid) \
            and recv in blocks.by_proc:
        # A Proc RPyYARV made: run its block here instead of going out to
        # CRuby and straight back in through the block callback.
        return _block_send(frame, w_ci, recv_at, argc, blocks.by_proc[recv])
    if w_ci.mid == CORE_ALIAS or w_ci.mid == CORE_UNDEF:
        return _core_method(frame, w_ci, recv, recv_at, argc)
    if vm_core.value != 0 and recv == vm_core.value:
        # #lambda and #proc would hand libruby a Proc over a block handle
        # that only lives for the extent of the call, and crash later.
        raise UnsupportedOperation(
            "RubyVM::FrozenCore#%s is not supported"
            % symbols.name_of(w_ci.mid))

    # Everything RPyYARV has not taken over goes back to CRuby.
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    if w_block is not None:
        if w_ci.blockarg:
            return _call_with_block(recv, w_ci.mid, args, w_block)
        try:
            return _call_with_block(recv, w_ci.mid, args, w_block)
        except block_mod.BlockBreak, e:
            # As above: only the send the block was written at catches it.
            if e.w_block is not w_block:
                raise
            return e.value
    # An entry survived here only by being private to a receiverless call, and
    # rb_funcallv would reach the trampoline for it anyway (CALL_FCALL).
    public_only = entry is not None and not w_ci.fcall
    if not debug.state.enabled:
        ret = rubycall.call(recv, w_ci.mid, args, public_only)
        # The callee may have run a Proc of ours, which cannot raise through
        # libruby's frames and parked its failure instead.
        _check_block_error()
        return ret
    debug.trace_enter(w_ci.mid, args)
    ret = rubycall.call(recv, w_ci.mid, args, public_only)
    _check_block_error()
    debug.trace_leave(w_ci.mid, ret)
    return ret


NEW = symbols.intern('new')
INITIALIZE = symbols.intern('initialize')
BLOCK_GIVEN = symbols.intern('block_given?')
ATTR_READER = symbols.intern('attr_reader')
ATTR_WRITER = symbols.intern('attr_writer')
ATTR_ACCESSOR = symbols.intern('attr_accessor')


def _is_attr_mid(mid):
    return (mid == ATTR_READER or mid == ATTR_WRITER
            or mid == ATTR_ACCESSOR)


def _is_identity_mid(mid):
    return (mid == helpers.EQ or mid == helpers.NEQ
            or mid == helpers.EQUAL_P)


def _attr_send(frame, entry, recv, recv_at, argc):
    """An attr_* entry: the shape-guarded ivar access dispatch.py compiles
    getinstancevariable to, without a frame."""
    if entry.kind == dispatch.KIND_ATTR_READER:
        if argc != 0:
            _arity_error(argc, 0, 0)
        _drop(frame, recv_at)
        debug.count_native()
        return dispatch.ivar_get(recv, entry.ivar)
    if argc != 1:
        _arity_error(argc, 1, 1)
    # Stored before the drop: ivar_set may allocate, and the frame marks it.
    v = frame.stack[recv_at + 1]
    dispatch.ivar_set(recv, entry.ivar, v)
    _drop(frame, recv_at)
    debug.count_native()
    return v


@unroll_safe
def _define_attrs(frame, w_ci, klass, recv_at, argc):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    # First, so a name CRuby rejects raises before anything is registered.
    ret = rubycall.call(klass, w_ci.mid, args)
    _install_attrs(klass, w_ci.mid, args)
    return ret


@dont_look_inside
def _install_attrs(klass, mid, args):
    """attr_* still runs in CRuby, so its own method entries stay there for
    reflection and for CRuby's callers; the registry gains native ones too."""
    for i in range(len(args)):
        name = _attr_name(args[i])
        if name == '':
            continue
        ivar = symbols.intern('@' + name)
        if mid != ATTR_WRITER:
            dispatch.define_attr(klass, symbols.intern(name), ivar,
                                 dispatch.KIND_ATTR_READER)
        if mid != ATTR_READER:
            dispatch.define_attr(klass, symbols.intern(name + '='), ivar,
                                 dispatch.KIND_ATTR_WRITER)


def _attr_name(v):
    if boot.is_symbol(v):
        return boot.sym_of(v)
    if not value.is_immediate(v) and boot.is_string(v):
        return boot.str_of(v)
    return ''


def _new_with_block(frame, entry, klass, recv_at, argc, w_block):
    """`Klass.new { }` run here rather than through CRuby's Class#new, which
    is what opt_new already does for the blockless form. Going out would hand
    initialize a Proc over a block handle that dies when Class#new returns."""
    obj = dispatch.alloc(klass)
    # In the caller's marked slot, since _enter drops it only once the
    # arguments are placed.
    frame.stack[recv_at] = obj
    _enter(frame, entry, obj, recv_at, argc, INITIALIZE, w_block)
    return obj


@unroll_safe
def _enter(frame, entry, recv, recv_at, argc, mid, w_block=None):
    """Move argc arguments into a fresh frame and run it; also invokesuper."""
    callee_iseq = entry.w_iseq
    callee = Frame(callee_iseq, recv, 0, entry)
    callee.block = w_block
    pc = 0
    if callee_iseq.simple_params:
        if argc != callee_iseq.nparams:
            _arity_error(argc, callee_iseq.nparams, callee_iseq.nparams)
        i = 0
        while i < argc:
            callee.locals[i] = frame.stack[recv_at + 1 + i]
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        # Copied out first: the codewriter refuses a virtualizable array
        # passed on, and the caller's frame keeps the values marked.
        given = [0] * argc
        i = 0
        while i < argc:
            given[i] = frame.stack[recv_at + 1 + i]
            i += 1
        pc = setup_params(callee_iseq, callee, given, False)
    _drop(frame, recv_at)
    debug.count_native()
    if not debug.state.enabled:
        return execute(callee_iseq, callee, pc)
    args = []
    i = 0
    while i < argc:
        args.append(callee.locals[i])
        i += 1
    debug.trace_enter(mid, args)
    ret = execute(callee_iseq, callee, pc)
    debug.trace_leave(mid, ret)
    return ret


def _refuse_iseq(w_iseq, mid):
    if w_iseq.unsupported != '':
        raise UnsupportedOperation("method '%s': %s"
                                   % (symbols.name_of(mid),
                                      w_iseq.unsupported))


@unroll_safe
def setup_params(w_iseq, callee, args, is_block):
    """vm_args.c setup_parameters_complex for positional arguments only:
    lead, then post off the tail, then optionals, then the rest Array.
    Answers the pc the opt table names (vm_args.c:906)."""
    lead = w_iseq.nparams
    opt_num = len(w_iseq.opt_table) - 1
    if opt_num < 0:
        opt_num = 0
    post_num = w_iseq.post_num
    rest = w_iseq.rest_start
    post_start = w_iseq.post_start
    # The loader checked all of these against nlocals; restated so the
    # codewriter sees every index into the virtualizable as non-negative.
    assert lead >= 0
    assert post_num >= 0
    # vm_args.c:594; a rest parameter makes the maximum unlimited.
    min_argc = lead + post_num
    max_argc = -1 if rest >= 0 else min_argc + opt_num
    n = len(args)
    if n < min_argc:
        if not is_block:
            _arity_error(n, min_argc, max_argc)
    elif max_argc >= 0 and n > max_argc:
        if not is_block:
            _arity_error(n, min_argc, max_argc)
        # arg_setup_block truncates instead of raising (vm_args.c:884).
        n = max_argc

    i = 0
    while i < lead:
        if i < n:
            callee.locals[i] = args[i]
        else:
            callee.locals[i] = value.Q_NIL
        i += 1

    given = n - min_argc
    if given < 0:
        given = 0
    filled = given if given < opt_num else opt_num
    i = 0
    while i < filled:
        callee.locals[lead + i] = args[lead + i]
        i += 1

    if rest >= 0:
        count = given - filled
        values = [0] * count
        i = 0
        while i < count:
            values[i] = args[lead + filled + i]
            i += 1
        # The caller's frame still holds these while the shim copies them
        # onto the machine stack.
        ary = rubycall.ary_new(values)
        assert rest >= 0
        callee.locals[rest] = ary

    if post_num > 0:
        assert post_start >= 0
        i = 0
        while i < post_num:
            take = n - post_num + i
            if take >= 0 and take < n:
                callee.locals[post_start + i] = args[take]
            else:
                callee.locals[post_start + i] = value.Q_NIL
            i += 1

    if opt_num > 0:
        return w_iseq.opt_table[filled]
    return 0


@dont_look_inside
def _arity_error(given, min_argc, max_argc):
    raise RubyException(boot.arity_error(given, min_argc, max_argc),
                        'ArgumentError')


@unroll_safe
def _opt_send(frame, mid, argc):
    """The send an opt_* instruction falls through to when its fast path
    answered Qundef, as vm_insnhelper.c's CALL_SIMPLE_METHOD does. The
    operands are still on the frame's stack, so they stay marked."""
    recv_at = frame.sp - argc - 1
    assert recv_at >= 0
    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    klass = promote(value.class_of(recv))
    entry = dispatch.lookup(klass, mid)
    if entry is not None and not entry.private:
        if entry.kind != dispatch.KIND_ISEQ:
            return _attr_send(frame, entry, recv, recv_at, argc)
        return _enter(frame, entry, recv, recv_at, argc, mid, None)
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    return rubycall.call(recv, mid, args)


@unroll_safe
def invoke_super(frame, w_ci):
    """A send's lookup, resumed above the running method's owner."""
    entry = frame.entry
    if entry is None:
        raise UnsupportedOperation(
            'super outside a method body is not supported')
    argc = w_ci.argc
    recv_at = frame.sp - argc - 1
    if recv_at < 0:
        raise UnsupportedOperation(
            "super with %d argument(s) underflows the stack" % argc)
    if not w_ci.simple:
        raise UnsupportedOperation(
            "super in '%s' passes arguments RPyYARV does not support"
            % symbols.name_of(entry.mid))

    rubycall.gc_stress_point()
    target = dispatch.lookup_super(entry.owner, entry.mid)
    if target is None:
        # rb_call_super needs a CRuby frame, which RPyYARV never has.
        raise UnsupportedOperation(
            "super from '%s' reaches a method RPyYARV did not define; "
            "calling CRuby's implementation of a superclass method is not "
            "supported" % symbols.name_of(entry.mid))
    if target.kind != dispatch.KIND_ISEQ:
        return _attr_send(frame, target, frame.stack[recv_at], recv_at, argc)
    return _enter(frame, target, frame.stack[recv_at], recv_at, argc,
                  entry.mid)


# `alias` and `undef` compile to a send of one of these (vm.c); RPyYARV has to
# see them, or its own registry keeps shadowing what they change in CRuby.
CORE_ALIAS = symbols.intern('core#set_method_alias')
CORE_UNDEF = symbols.intern('core#undef_method')


def _core_method(frame, w_ci, recv, recv_at, argc):
    if argc != 3 and w_ci.mid == CORE_ALIAS:
        raise UnsupportedOperation('core#set_method_alias needs 3 arguments')
    if argc != 2 and w_ci.mid == CORE_UNDEF:
        raise UnsupportedOperation('core#undef_method needs 2 arguments')
    cbase = frame.stack[recv_at + 1]
    if value.is_immediate(cbase) or not boot.is_class(cbase):
        raise UnsupportedOperation('alias or undef outside a class body')
    name = _sym_mid(frame.stack[recv_at + 2])
    if w_ci.mid == CORE_UNDEF:
        dispatch.undefine(cbase, name)
        args = [cbase, frame.stack[recv_at + 2]]
        _drop(frame, recv_at)
        ret = rubycall.call(recv, w_ci.mid, args)
        helpers.refresh()
        return ret
    old = _sym_mid(frame.stack[recv_at + 3])
    entry = dispatch.own_lookup(cbase, old)
    dispatch.undefine(cbase, name)
    if entry is not None:
        # An RPyYARV method: the alias is a second name for the same body.
        if entry.kind != dispatch.KIND_ISEQ:
            dispatch.define_attr(cbase, name, entry.ivar, entry.kind)
        else:
            dispatch.define(cbase, name, entry.w_iseq, entry.private)
        _drop(frame, recv_at)
        return value.Q_NIL
    args = [cbase, frame.stack[recv_at + 2], frame.stack[recv_at + 3]]
    _drop(frame, recv_at)
    ret = rubycall.call(recv, w_ci.mid, args)
    helpers.refresh()
    return ret


@dont_look_inside
def _sym_mid(v):
    if not boot.is_symbol(v):
        raise UnsupportedOperation('alias or undef names something '
                                   'that is not a Symbol')
    return symbols.intern(boot.sym_of(v))


class _Blocks(object):
    """Blocks C refers to, by integer handle only: RPython's GC moves its
    objects, so no pointer may cross. A handle rb_block_call holds is given
    back when that call returns; one a Proc was made over never is, since the
    Proc outlives every frame that could tell when the last reference died."""
    def __init__(self):
        self.table = []         # handle -> W_Block, None for a free slot
        self.free = []          # handles the transient path gave back
        self.by_proc = {}       # a materialised Proc -> the block behind it
        self.error = None       # an RPython error the callback could not raise
        self.exc = None         # likewise, a Ruby exception
        self.jump = None        # likewise, a break or a non-local return


blocks = _Blocks()


def _alloc_handle(w_block):
    if len(blocks.free) > 0:
        h = blocks.free.pop()
        blocks.table[h] = w_block
        return h
    blocks.table.append(w_block)
    return len(blocks.table) - 1


def _release_handle(h):
    blocks.table[h] = None
    blocks.free.append(h)


class _Proxy(object):
    # Quasi-immutable, so the compare below folds away; see value._Classes for
    # why a prebuilt instance cannot use a plain immutable field.
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


# rb_block_param_proxy's stand-in: what getblockparamproxy pushes instead of
# building a Proc (insns.def:144). A Symbol, so it needs no marking, and it
# never leaves the three places the compiler emits that instruction for.
proxy = _Proxy()

PROXY_NAME = '__rpyyarv_block_param_proxy__'


def block_callback(handle, argc, argv):
    """Called from C, inside rb_block_call or a materialised Proc. No RPython
    exception may escape into libruby, so a failure is re-raised once the call
    has returned."""
    if blocks.error is not None or blocks.exc is not None \
            or blocks.jump is not None:
        return boot.as_value(value.Q_NIL)
    w_block = blocks.table[handle]
    if w_block is None:
        blocks.error = UnsupportedOperation(
            'a block was called after its handle was released')
        return boot.as_value(value.Q_NIL)
    args = boot.read_values(argv, argc)
    try:
        return boot.as_value(call_block(w_block, args))
    except RubyException, e:
        # Held: the RPython field it waits in is not something CRuby scans.
        gcroots.hold(e.value)
        blocks.exc = e
        return _park_unwind()
    except block_mod.BlockJump, e:
        gcroots.hold(e.value)
        blocks.jump = e
        return _park_unwind()
    except RPyYarvError, e:
        blocks.error = e
        return _park_unwind()
    except StackOverflow:
        # Parked like the rest: returning normally would let the CRuby method
        # call the block again, one exhausted stack later.
        check_stack_overflow()
        blocks.error = UnsupportedOperation(STACK_TOO_DEEP)
        return _park_unwind()


STACK_TOO_DEEP = 'the call is nested too deeply for RPyYARV\'s stack'


@dont_look_inside
def _park_unwind():
    """The block has to leave the CRuby method running it, and an RPython
    exception cannot cross libruby's frames; the shim raises on its behalf
    and the rb_protect boundary hands control back here."""
    boot.set_block_unwind()
    return boot.as_value(value.Q_NIL)


TRAMP_OK = 0
TRAMP_RAISE = 1
TRAMP_UNSUPPORTED = 2
TRAMP_UNWIND = 3


def trampoline_callback(self_v, rid, argc, argv, blockv, statusp, errp):
    """Called from C when CRuby dispatched a send to a method RPyYARV defined.
    No RPython exception may reach libruby, so a failure leaves through
    statusp/errp and the shim raises it as a Ruby one."""
    boot.store_int(statusp, TRAMP_OK)
    boot.store_value(errp, value.Q_NIL)
    recv = boot.as_signed(self_v)
    mid = rubycall.mid_of_rid(boot.as_signed(rid))
    # argv still lives on CRuby's VM stack for the whole call, so the copy
    # below needs no root of its own until it lands in the callee's frame.
    args = boot.read_values(argv, argc)
    w_block = None
    proc_v = boot.as_signed(blockv)
    if proc_v != value.Q_NIL:
        w_block = block_mod.from_proc(proc_v)
    try:
        return boot.as_value(_from_cruby(recv, mid, args, w_block))
    except RubyException, e:
        boot.store_int(statusp, TRAMP_RAISE)
        boot.store_value(errp, e.value)
    except block_mod.BlockJump, e:
        # Aimed past this call, at a frame CRuby's own frames now sit under;
        # the shim raises so libruby unwinds them, and the rb_protect the
        # RPyYARV caller is under hands control back.
        gcroots.hold(e.value)
        blocks.jump = e
        boot.store_int(statusp, TRAMP_UNWIND)
    except block_mod.BlockNext:
        _tramp_failed(statusp, errp,
                      'next out of a method RPyYARV ran for CRuby is not '
                      'supported')
    except boot.RubyError, e:
        _tramp_failed(statusp, errp, "a call to '%s' failed" % e.mid)
    except RPyYarvError, e:
        _tramp_failed(statusp, errp, e.msg)
    except StackOverflow:
        check_stack_overflow()
        _tramp_failed(statusp, errp, STACK_TOO_DEEP)
    return boot.as_value(value.Q_NIL)


@dont_look_inside
def _tramp_failed(statusp, errp, msg):
    boot.store_int(statusp, TRAMP_UNSUPPORTED)
    boot.store_value(errp, boot.str_new('[rpyyarv] %s' % msg))


def _from_cruby(recv, mid, args, w_block):
    """The send half of the trampoline: the registry's own lookup and frame
    setup, with the arguments CRuby already parsed."""
    if mid == rubycall.NO_MID:
        raise UnsupportedOperation(
            'CRuby dispatched a method name RPyYARV never interned')
    entry = dispatch.lookup_from_cruby(value.class_of(recv), mid)
    if entry is None:
        raise UnsupportedOperation(
            "CRuby dispatched '%s' to RPyYARV, which no longer defines it"
            % symbols.name_of(mid))
    if entry.kind != dispatch.KIND_ISEQ:
        return _attr_from_cruby(entry, recv, args)
    callee_iseq = entry.w_iseq
    callee = Frame(callee_iseq, recv, 0, entry)
    callee.block = w_block
    pc = 0
    argc = len(args)
    if callee_iseq.simple_params:
        if argc != callee_iseq.nparams:
            _arity_error(argc, callee_iseq.nparams, callee_iseq.nparams)
        i = 0
        while i < argc:
            callee.locals[i] = args[i]
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        pc = setup_params(callee_iseq, callee, args, False)
    debug.count_native()
    return execute(callee_iseq, callee, pc)


def _attr_from_cruby(entry, recv, args):
    """_from_cruby's accessor case; CRuby's argv is already a marked buffer."""
    if entry.kind == dispatch.KIND_ATTR_READER:
        if len(args) != 0:
            _arity_error(len(args), 0, 0)
        debug.count_native()
        return dispatch.ivar_get(recv, entry.ivar)
    if len(args) != 1:
        _arity_error(len(args), 1, 1)
    dispatch.ivar_set(recv, entry.ivar, args[0])
    debug.count_native()
    return args[0]


@dont_look_inside
def _call_with_block(recv, mid, args, w_block):
    handle = _alloc_handle(w_block)
    ret = value.Q_NIL
    try:
        try:
            ret = rubycall.call_with_block(recv, mid, args, handle)
        except RubyException:
            # The CRuby method failed; whatever the block parked before that
            # is the reason, and takes precedence.
            _check_block_error()
            raise
    finally:
        _release_handle(handle)
    _check_block_error()
    return ret


def _check_block_error():
    """What a callback into RPyYARV could not raise through libruby's frames,
    now that the shim's RPyYARV::Unwind has brought control back."""
    exc = blocks.exc
    if exc is not None:
        blocks.exc = None
        gcroots.release(exc.value)
        raise exc
    jump = blocks.jump
    if jump is not None:
        blocks.jump = None
        gcroots.release(jump.value)
        raise jump
    err = blocks.error
    if err is not None:
        blocks.error = None
        raise err


@dont_look_inside
def _to_proc(w_block):
    """A real Proc for a block that is about to escape, as
    rb_vm_bh_to_procval builds one (vm_insnhelper.c:543). Memoised, so a
    block has one Proc identity; the handle it carries is never released."""
    if w_block is None:
        return value.Q_NIL
    if w_block.proc_value != 0:
        return w_block.proc_value
    v = boot.proc_new(_alloc_handle(w_block))
    w_block.proc_value = v
    blocks.by_proc[v] = w_block
    return v


TO_PROC = symbols.intern('to_proc')
CALL = symbols.intern('call')
YIELD = symbols.intern('yield')
AREF = symbols.intern('[]')
EQQ_ = symbols.intern('===')


def _is_proxy_call(mid):
    """The proxy runs the block itself for these; anything else makes it
    build the Proc first, as Proc#arity and friends need a real one."""
    return mid == CALL or mid == YIELD or mid == AREF or mid == EQQ_


@dont_look_inside
def _block_from_value(frame, v):
    """The block a `&arg` call site passes on, as vm_caller_setup_arg_block
    reads it (vm_args.c:1116)."""
    if v == value.Q_NIL:
        return None
    if v == proxy.value:
        # The frame's own block, without ever having built a Proc for it.
        return frame.block
    if v in blocks.by_proc:
        return blocks.by_proc[v]
    if boot.is_symbol(v):
        return block_mod.from_symbol(symbols.intern(boot.sym_of(v)))
    if not value.is_immediate(v) and boot.is_proc(v):
        return block_mod.from_proc(v)
    # vm_to_proc, vm_args.c:1044.
    p = rubycall.call0(v, TO_PROC)
    if value.is_immediate(p) or not boot.is_proc(p):
        raise UnsupportedOperation(
            'a &block argument that is not a Proc, a Symbol or nil and whose '
            '#to_proc did not answer a Proc is not supported')
    return block_mod.from_proc(p)


@unroll_safe
def _block_send(frame, w_ci, recv_at, argc, w_block):
    """A send whose receiver stands for a block RPyYARV holds: the block-param
    proxy (compile.c:9564), or a Proc it materialised itself."""
    args = [0] * argc
    i = 0
    while i < argc:
        args[i] = frame.stack[recv_at + 1 + i]
        i += 1
    _drop(frame, recv_at)
    if _is_proxy_call(w_ci.mid):
        if w_block is None:
            raise UnsupportedOperation('the block parameter is nil')
        return call_block(w_block, args)
    return rubycall.call(_to_proc(w_block), w_ci.mid, args)


@unroll_safe
def call_block(w_block, args):
    """Run a block's ISeq in a frame whose locals chain to the defining one."""
    if w_block.kind != block_mod.KIND_ISEQ:
        return _call_foreign_block(w_block, args)
    b_iseq = w_block.w_iseq
    outer = w_block.frame
    callee = Frame(b_iseq, outer.self_val, outer.cref, outer.entry)
    callee.defining_frame = outer
    callee.block = w_block.outer
    callee.own_block = w_block
    if b_iseq.autosplat and len(args) == 1:
        args = _autosplat(args)
    pc = 0
    if b_iseq.simple_params:
        n = len(args)
        if n > b_iseq.nparams:
            n = b_iseq.nparams
        i = 0
        while i < n:
            callee.locals[i] = args[i]
            i += 1
    else:
        pc = setup_params(b_iseq, callee, args, True)
    try:
        return execute(b_iseq, callee, pc)
    except block_mod.BlockNext, e:
        return e.value


@dont_look_inside
def _call_foreign_block(w_block, args):
    """A block that is not RPyYARV's own: a Proc from CRuby, or `&:sym`
    (rb_sym_to_proc, vm_insnhelper.c:552)."""
    if w_block.kind == block_mod.KIND_PROC:
        return rubycall.call(w_block.proc_value, CALL, args)
    if len(args) == 0:
        raise UnsupportedOperation('a &:symbol block needs a receiver')
    rest = []
    i = 1
    while i < len(args):
        rest.append(args[i])
        i += 1
    return rubycall.call(args[0], w_block.mid, rest)


@dont_look_inside
def _autosplat(args):
    """One yielded value spread over several block parameters. TODO: CRuby
    asks for to_ary (vm_args.c:863), this only takes a real Array."""
    v = args[0]
    if value.is_immediate(v) or not boot.is_array(v):
        return args
    n = boot.ary_len(v)
    out = [0] * n
    i = 0
    while i < n:
        out[i] = boot.ary_entry(v, i)
        i += 1
    return out


@unroll_safe
def _outer_frame(frame, level):
    """The frame `level` steps up the block chain; reading its locals from a
    trace forces that frame's virtualizable."""
    f = frame
    i = 0
    while i < level:
        f = f.defining_frame
        if f is None:
            raise UnsupportedOperation(
                'a local at level %d has no enclosing scope' % level)
        i += 1
    return f


@unroll_safe
def invoke_block(frame, w_ci):
    w_block = frame.block
    if w_block is None:
        raise UnsupportedOperation('yield without a block')
    argc = w_ci.argc
    at = frame.sp - argc
    if at < 0:
        raise UnsupportedOperation(
            'yield with %d argument(s) underflows the stack' % argc)
    args = [0] * argc
    i = 0
    while i < argc:
        args[i] = frame.stack[at + i]
        i += 1
    _drop(frame, at)
    return call_block(w_block, args)


class Throw(object):
    """A throw in flight, as vm_exec_handle_exception takes it. Not an
    exception itself; _rethrow turns it back into one."""
    def __init__(self, kind, value, w_block=None, name='raise',
                 target=None):
        self.kind = kind
        self.value = value
        self.w_block = w_block
        # PENDING_RETURN: the frame the return is aimed at.
        self.target = target
        self.name = name


def _rethrow(throw):
    if throw.kind == PENDING_RAISE:
        raise RubyException(throw.value, throw.name)
    if throw.kind == PENDING_BREAK:
        raise block_mod.BlockBreak(throw.w_block, throw.value)
    if throw.kind == PENDING_RETURN:
        raise block_mod.BlockReturn(throw.target, throw.value)
    raise block_mod.BlockNext(throw.value)


# A defining-frame chain longer than this is a corrupt one; the walk has to
# terminate for the tracer.
MAX_SCOPES = 256


def _return_target(frame):
    """The frame a non-local return leaves: the outermost of the chain the
    block was written in, which is CRuby's local EP (vm_insnhelper.c:1834)."""
    f = frame
    n = 0
    while f.defining_frame is not None and n < MAX_SCOPES:
        f = f.defining_frame
        n += 1
    return f


@dont_look_inside
def _local_jump_error(mesg, v, reason):
    return RubyException(boot.local_jump_error(mesg, v, reason), 'return')


def _return(frame, v):
    """`return` from a block. The target has to still be running, and has to
    be a method or the toplevel; anything else is the orphaned-Proc case
    vm_throw_start answers with a LocalJumpError (vm_insnhelper.c:1926)."""
    target = _return_target(frame)
    if target.dead or not target.w_iseq.catches_return:
        raise _local_jump_error('unexpected return', v, optable.TAG_RETURN)
    raise block_mod.BlockReturn(target, v)


def _throw(frame, throw_state, v):
    tag = throw_state & optable.TAG_MASK
    if tag == optable.TAG_NEXT:
        raise block_mod.BlockNext(v)
    if tag == optable.TAG_BREAK:
        w_block = frame.own_block
        if w_block is None:
            raise UnsupportedOperation('break outside a block')
        raise block_mod.BlockBreak(w_block, v)
    if tag == optable.TAG_RETURN:
        _return(frame, v)
    if tag == optable.TAG_NONE:
        # vm_throw_continue: re-raise what this catch ISeq runs under.
        if frame.pending_kind == PENDING_NONE:
            raise UnsupportedOperation(
                'throw 0 outside a rescue or ensure body')
        _rethrow(Throw(frame.pending_kind, frame.pending_value,
                       frame.pending_block, 'raise', frame.pending_frame))
    if tag == optable.TAG_RETRY:
        raise UnsupportedOperation('retry is not supported')
    raise UnsupportedOperation(
        'throw with tag %d (redo) is not supported' % tag)


def _catch_for(iseq, epc, kind):
    """The first catch-table entry covering epc, in CRuby's search order
    (vm.c:2911). A break or a next takes only an ensure."""
    catches = iseq.catches
    i = 0
    while i < len(catches):
        entry = catches[i]
        if entry.start < epc and epc <= entry.end:
            if entry.kind == CATCH_ENSURE or kind == PENDING_RAISE:
                return entry
        i += 1
    return None


def _run_catch(frame, entry, throw):
    """A catch ISeq runs in its own frame, chained to the raising one's
    locals the way vm.c:3014 pushes it with the previous EP."""
    w_iseq = entry.w_iseq
    callee = Frame(w_iseq, frame.self_val, frame.cref, frame.entry)
    callee.defining_frame = frame
    callee.block = frame.block
    callee.own_block = frame.own_block
    if len(callee.locals) > 0:
        # Local 0 is `$!`; for a break or a next nothing reads it.
        callee.locals[0] = throw.value if throw.kind == PENDING_RAISE \
            else value.Q_NIL
    callee.pending_kind = throw.kind
    callee.pending_value = throw.value
    callee.pending_block = throw.w_block
    callee.pending_frame = throw.target
    return _run_with_errinfo(w_iseq, callee, callee.locals[0]
                             if len(callee.locals) > 0 else value.Q_NIL)


def _run_with_errinfo(w_iseq, callee, errinfo):
    """`$!` and a bare `raise` read ec->errinfo, since RPyYARV pushes no CRuby
    rescue frame for rb_ec_get_errinfo to find."""
    prev = rubycall.swap_errinfo(errinfo)
    try:
        return execute(w_iseq, callee)
    finally:
        rubycall.swap_errinfo(prev)


def _unwind(iseq, frame, throw, epc):
    """Run the entries covering epc until one completes, and answer the pc to
    resume at; re-raises when the frame handles nothing."""
    while True:
        entry = _catch_for(iseq, epc, throw.kind)
        if entry is None:
            _rethrow(throw)
        frame.reset_sp(entry.sp)
        frame.pc = entry.cont
        try:
            result = _run_catch(frame, entry, throw)
        except RubyException, e:
            throw = Throw(PENDING_RAISE, e.value, None, e.name)
        except block_mod.BlockBreak, e:
            throw = Throw(PENDING_BREAK, e.value, e.w_block)
        except block_mod.BlockReturn, e:
            throw = Throw(PENDING_RETURN, e.value, None, 'return', e.frame)
        except block_mod.BlockNext, e:
            throw = Throw(PENDING_NEXT, e.value)
        else:
            frame.reset_sp(entry.sp)
            frame.push(result)
            return entry.cont
        # The catch ISeq threw in turn; cont is where the frame's pc stands.
        epc = entry.cont


def install():
    boot.install_block_callback(block_callback)
    boot.install_trampoline_callback(trampoline_callback)
    gcroots.register_blocks(blocks)
    # A Symbol, so it is an immediate no mark hook has to reach.
    proxy.value = boot.sym_new(PROXY_NAME)


@unroll_safe
def _local_frame(frame, packed):
    """The frame a packed getlocal-style operand names."""
    if packed == (packed & optable.LOCAL_SLOT_MASK):
        return frame
    return _outer_frame(frame, packed >> optable.LOCAL_LEVEL_SHIFT)


@unroll_safe
def _drop(frame, sp):
    while frame.sp > sp:
        frame.pop()


@dont_look_inside
def _to_s(v):
    if rubycall.is_string(v):
        return v
    return rubycall.call0(v, TO_S)


@dont_look_inside
def _concat(parts):
    return boot.str_concat(parts)


@unroll_safe
def _newarray(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('newarray %d underflows the stack' % n)
    # Copied but not popped: the frame marks them until the shim has them on
    # the machine stack.
    values = [0] * n
    i = 0
    while i < n:
        values[i] = frame.stack[at + i]
        i += 1
    v = rubycall.ary_new(values)
    _drop(frame, at)
    return v


@unroll_safe
def _newhash(frame, n):
    """n/2 key/value pairs, left in the marked frame until each rb_hash_aset
    has copied them into the Hash."""
    at = frame.sp - n
    if at < 0 or n % 2 != 0:
        raise UnsupportedOperation('newhash %d underflows the stack' % n)
    h = rubycall.hash_new(n // 2)
    i = 0
    while i < n:
        rubycall.hash_aset(h, frame.stack[at + i], frame.stack[at + i + 1])
        i += 2
    _drop(frame, at)
    return h


@unroll_safe
def _dupn(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('dupn %d underflows the stack' % n)
    i = 0
    while i < n:
        frame.push(frame.stack[at + i])
        i += 1


@unroll_safe
def _adjuststack(frame, n):
    if frame.sp - n < 0:
        raise UnsupportedOperation('adjuststack %d underflows the stack' % n)
    i = 0
    while i < n:
        frame.pop()
        i += 1


@unroll_safe
def _reverse(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('opt_reverse %d underflows the stack' % n)
    i = 0
    while i < n // 2:
        lo = at + i
        hi = frame.sp - 1 - i
        assert lo >= 0
        assert hi >= 0
        v = frame.stack[lo]
        frame.stack[lo] = frame.stack[hi]
        frame.stack[hi] = v
        i += 1


@dont_look_inside
def _expand(frame, v, n):
    if value.is_immediate(v) or not boot.is_array(v):
        raise UnsupportedOperation('expandarray needs an Array, got %s'
                                   % value.repr_of(v))
    size = boot.ary_len(v)
    i = n - 1
    while i >= 0:
        if i < size:
            frame.push(boot.ary_entry(v, i))
        else:
            frame.push(value.Q_NIL)
        i -= 1


class _VMCore(object):
    # Quasi-immutable, not immutable: a prebuilt instance's plain immutable
    # field would fold to the 0 it holds before boot fills it.
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


vm_core = _VMCore()


@dont_look_inside
def _vm_core():
    """RubyVM::FrozenCore, receiver of the core# methods
    (vm_insnhelper.c:5668)."""
    if vm_core.value == 0:
        v = boot.vm_core()
        boot.gc_register(v)
        vm_core.value = v
    return vm_core.value


@unroll_safe
def _const_path(frame, path):
    """vm_get_ev_const_chain; a leading empty segment is `::Foo`."""
    base = _const_base(frame)
    i = 0
    if symbols.name_of(path[0]) == '':
        base = value.core_class(value.C_OBJECT)
        i = 1
    while i < len(path):
        base = dispatch.const_get(base, path[i])
        i += 1
    return base


def _const_base(frame):
    """The cref's constant base. In a method body that is the class the def
    was written in, which rb_const_get then searches with its ancestors.
    TODO: a nested cref chain, so `class A; X=1; class B; def f; X; end` finds
    A's constant the way a lexical scope walk would."""
    if frame.cref != 0:
        return frame.cref
    entry = frame.entry
    if entry is not None and entry.cref != 0:
        return entry.cref
    return value.core_class(value.C_OBJECT)


def _defineclass(mid, w_body, cbase, super_v):
    klass = dispatch.define_class(cbase, mid, super_v)
    ret = execute(w_body, Frame(w_body, klass, klass))
    # Reopening a class is where CRuby-side operator redefinitions show up.
    helpers.refresh()
    return ret


@dont_look_inside
def _opt_new_alloc(klass):
    """A fresh instance, or 0 for the miss branch. Only classes RPyYARV made:
    nothing else is known to have kept Class#new."""
    if not dispatch.is_known_class(klass):
        return 0
    return dispatch.alloc(klass)


EQQ = symbols.intern('===')


@dont_look_inside
def _checkmatch(target, pattern, flag):
    """vm_check_match, vm_insnhelper.c:5772."""
    if flag & optable.CHECKMATCH_ARRAY:
        if value.is_immediate(pattern) or not boot.is_array(pattern):
            raise UnsupportedOperation(
                'checkmatch with an array flag needs an Array of patterns')
        n = boot.ary_len(pattern)
        i = 0
        while i < n:
            if _match_one(target, boot.ary_entry(pattern, i), flag):
                return value.Q_TRUE
            i += 1
        return value.Q_FALSE
    return value.newbool(_match_one(target, pattern, flag))


def _match_one(target, pattern, flag):
    kind = flag & optable.CHECKMATCH_TYPE_MASK
    if kind == optable.CHECKMATCH_TYPE_WHEN:
        return value.is_true(pattern)
    is_module = not value.is_immediate(pattern) and boot.is_class(pattern)
    if kind == optable.CHECKMATCH_TYPE_RESCUE and not is_module:
        raise UnsupportedOperation('class or module required for rescue clause')
    if is_module:
        # Module#=== is rb_obj_is_kind_of, so going straight there skips a send.
        # TODO: a subclass redefining #=== is ignored, as in vm_opt_*.
        return boot.obj_is_kind_of(target, pattern)
    return value.is_true(rubycall.call1(pattern, EQQ, target))


def _binop(frame, recv, arg, mid):
    """Both operands back on the stack, where the mark hook reaches them,
    before the send that may allocate."""
    frame.push(recv)
    frame.push(arg)
    return _opt_send(frame, mid, 1)


def _unop(frame, recv, mid):
    frame.push(recv)
    return _opt_send(frame, mid, 0)


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'],
                      get_printable_location=get_printable_location)


def _epc(iseq, pc):
    """Catch-table ranges are against the pc *after* the raising instruction."""
    return pc + 1 + optable.NUM_OPERANDS[iseq.code[pc]]


def execute(iseq, frame, pc=0):
    """Two shapes on purpose: the handler shape below stops the JIT inlining
    the call, so an ISeq with no catch table keeps a plain tail call instead.
    iseq is green, so the branch folds away."""
    if iseq.catches_return:
        return _execute_returnable(iseq, frame, pc)
    if len(iseq.catches) == 0:
        gcroots.push_frame(frame)
        try:
            return _execute(iseq, frame, pc)
        finally:
            gcroots.pop_frame(frame)
    return _execute_guarded(iseq, frame, pc)


def _execute_returnable(iseq, frame, pc):
    """A frame a `return` inside one of its blocks names. The unwinding has
    run this frame's own ensure entries by the time it gets here; what is
    left is to answer the value, as vm_throw_start's valid_return does."""
    try:
        try:
            if len(iseq.catches) == 0:
                gcroots.push_frame(frame)
                try:
                    return _execute(iseq, frame, pc)
                finally:
                    gcroots.pop_frame(frame)
            return _execute_guarded(iseq, frame, pc)
        except block_mod.BlockReturn, e:
            if e.frame is not frame:
                raise
            return e.value
    finally:
        frame.dead = True


def _execute_guarded(iseq, frame, pc):
    gcroots.push_frame(frame)
    try:
        while True:
            try:
                return _execute(iseq, frame, pc)
            except RubyException, e:
                pc = _unwind(iseq, frame,
                             Throw(PENDING_RAISE, e.value, None, e.name),
                             _epc(iseq, frame.pc))
            except block_mod.BlockBreak, e:
                pc = _unwind(iseq, frame,
                             Throw(PENDING_BREAK, e.value, e.w_block),
                             _epc(iseq, frame.pc))
            except block_mod.BlockReturn, e:
                pc = _unwind(iseq, frame,
                             Throw(PENDING_RETURN, e.value, None, 'return',
                                   e.frame),
                             _epc(iseq, frame.pc))
            except block_mod.BlockNext, e:
                pc = _unwind(iseq, frame, Throw(PENDING_NEXT, e.value),
                             _epc(iseq, frame.pc))
    finally:
        gcroots.pop_frame(frame)


def _execute(iseq, frame, pc):
    while True:
        jitdriver.jit_merge_point(iseq=iseq, pc=pc, frame=frame)
        # Only an unwinding exception reads this; a store to a virtualizable
        # field costs a trace nothing.
        frame.pc = pc
        # Rebound each iteration: hoisting it would leave a live variable
        # across the merge point that is neither green nor red.
        code = iseq.code
        opcode = code[pc]
        if debug.state.enabled:
            debug.trace_insn(iseq, pc, frame)
        pc += 1

        if opcode == insns.NOP:
            pass
        elif opcode == insns.PUTNIL:
            frame.push(value.Q_NIL)
        elif opcode == insns.PUTSELF:
            frame.push(frame.self_val)
        elif opcode == insns.PUTOBJECT:
            idx = code[pc]
            pc += 1
            frame.push(iseq.consts[idx])
        elif opcode == insns.PUTSTRING or opcode == insns.PUTCHILLEDSTRING:
            idx = code[pc]
            pc += 1
            # A literal is a fresh String on every evaluation in Ruby.
            frame.push(rubycall.call0(iseq.consts[idx], DUP))
        elif opcode == insns.GETLOCAL:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            if packed == idx:
                frame.push(frame.locals[idx])
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                frame.push(_outer_frame(frame, level).locals[idx])
        elif opcode == insns.SETLOCAL:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            if packed == idx:
                frame.locals[idx] = frame.pop()
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                _outer_frame(frame, level).locals[idx] = frame.pop()
        elif opcode == insns.GETBLOCKPARAMPROXY:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            if f.block_param_set:
                frame.push(f.locals[idx])
            elif f.block is None:
                frame.push(value.Q_NIL)
            else:
                frame.push(proxy.value)
        elif opcode == insns.GETBLOCKPARAM:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            if not f.block_param_set:
                f.locals[idx] = _to_proc(f.block)
                f.block_param_set = True
            frame.push(f.locals[idx])
        elif opcode == insns.SETBLOCKPARAM:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            f.locals[idx] = frame.pop()
            f.block_param_set = True
        elif opcode == insns.DUP:
            v = frame.pop()
            frame.push(v)
            frame.push(v)
        elif opcode == insns.POP:
            frame.pop()
        elif opcode == insns.SWAP:
            a = frame.pop()
            b = frame.pop()
            frame.push(a)
            frame.push(b)
        elif opcode == insns.EXPANDARRAY:
            n = code[pc]
            pc += 1
            _expand(frame, frame.pop(), n)
        elif opcode == insns.OPT_PLUS:
            b = frame.pop()
            a = frame.pop()
            v = helpers.add(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.PLUS))
        elif opcode == insns.OPT_MINUS:
            b = frame.pop()
            a = frame.pop()
            v = helpers.sub(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.MINUS))
        elif opcode == insns.OPT_MULT:
            b = frame.pop()
            a = frame.pop()
            v = helpers.mul(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.MULT))
        elif opcode == insns.OPT_LT:
            b = frame.pop()
            a = frame.pop()
            v = helpers.lt(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.LT))
        elif opcode == insns.OPT_GT:
            b = frame.pop()
            a = frame.pop()
            v = helpers.gt(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.GT))
        elif opcode == insns.OPT_LE:
            b = frame.pop()
            a = frame.pop()
            v = helpers.le(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.LE))
        elif opcode == insns.OPT_GE:
            b = frame.pop()
            a = frame.pop()
            v = helpers.ge(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.GE))
        elif opcode == insns.OPT_EQ:
            b = frame.pop()
            a = frame.pop()
            v = helpers.eq(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.EQ))
        elif opcode == insns.OBJTOSTRING:
            frame.push(_to_s(frame.pop()))
        elif opcode == insns.ANYTOSTRING:
            v_str = frame.pop()
            v_val = frame.pop()
            if not rubycall.is_string(v_str):
                raise UnsupportedOperation('to_s on %s did not return a String'
                                           % value.repr_of(v_val))
            frame.push(v_str)
        elif opcode == insns.CONCATSTRINGS:
            n = code[pc]
            pc += 1
            parts = [0] * n
            i = n - 1
            while i >= 0:
                parts[i] = frame.pop()
                i -= 1
            frame.push(_concat(parts))
        elif opcode == insns.OPT_DIV:
            b = frame.pop()
            a = frame.pop()
            v = helpers.div(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.DIV))
        elif opcode == insns.OPT_MOD:
            b = frame.pop()
            a = frame.pop()
            v = helpers.mod(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.MOD))
        elif opcode == insns.OPT_NEQ:
            b = frame.pop()
            a = frame.pop()
            v = helpers.neq(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.NEQ))
        elif opcode == insns.GETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            frame.push(dispatch.ivar_get(frame.self_val, mid))
        elif opcode == insns.SETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            dispatch.ivar_set(frame.self_val, mid, frame.pop())
        elif opcode == insns.PUTSPECIALOBJECT:
            kind = code[pc]
            pc += 1
            if kind == optable.SPECIAL_OBJECT_VMCORE:
                frame.push(_vm_core())
            else:
                # CBASE and CONST_BASE differ only for a singleton class body.
                frame.push(_const_base(frame))
        elif opcode == insns.OPT_GETCONSTANT_PATH:
            idx = code[pc]
            pc += 1
            frame.push(_const_path(frame, iseq.paths[idx]))
        elif opcode == insns.SETCONSTANT:
            mid = code[pc]
            pc += 1
            cbase = frame.pop()
            dispatch.const_set(cbase, mid, frame.pop())
        elif opcode == insns.DEFINECLASS:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            flags = code[pc + 2]
            pc += 3
            super_v = frame.pop()
            cbase = frame.pop()
            if not flags & optable.DEFINECLASS_FLAG_HAS_SUPERCLASS:
                super_v = 0
            frame.push(_defineclass(mid, w_body, cbase, super_v))
        elif opcode == insns.OPT_NEW:
            w_ci = iseq.callinfos[code[pc]]
            target = code[pc + 1]
            pc += 2
            at = frame.sp - w_ci.argc - 1
            below = at - 1
            if below < 0:
                raise UnsupportedOperation(
                    'opt_new with %d argument(s) underflows the stack'
                    % w_ci.argc)
            assert at >= 1
            assert below >= 0
            obj = _opt_new_alloc(frame.stack[at])
            if obj == 0:
                pc = target
            else:
                # Receiver of the `initialize` send that follows, and the
                # slot below it, which becomes that send's result.
                frame.stack[at] = obj
                frame.stack[below] = obj
        elif opcode == insns.DEFINEMETHOD:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            pc += 2
            define_method(frame, mid, w_body)
        elif opcode == insns.DEFINESMETHOD:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            pc += 2
            dispatch.define_singleton(frame.pop(), mid, w_body, frame.cref)
        elif opcode == insns.OPT_SEND_WITHOUT_BLOCK:
            idx = code[pc]
            pc += 1
            frame.push(invoke(frame, iseq.callinfos[idx]))
        elif opcode == insns.SEND:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            w_ci = iseq.callinfos[idx]
            w_block = None
            if block != NO_BLOCK_ISEQ:
                w_block = block_mod.W_Block(iseq.iseqs[block], frame,
                                            frame.block)
            frame.push(invoke(frame, w_ci, w_block))
        elif opcode == insns.INVOKEBLOCK:
            idx = code[pc]
            pc += 1
            frame.push(invoke_block(frame, iseq.callinfos[idx]))
        elif opcode == insns.INVOKESUPER:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            if block != NO_BLOCK_ISEQ:
                raise UnsupportedOperation(
                    'super with a block is not supported')
            frame.push(invoke_super(frame, iseq.callinfos[idx]))
        elif opcode == insns.JUMP:
            target = code[pc]
            pc += 1
            backward = target < pc
            pc = target
            if backward:
                jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHIF:
            target = code[pc]
            pc += 1
            if value.is_true(frame.pop()):
                backward = target < pc
                pc = target
                if backward:
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHUNLESS:
            target = code[pc]
            pc += 1
            if not value.is_true(frame.pop()):
                backward = target < pc
                pc = target
                if backward:
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.CHECKMATCH:
            flag = code[pc]
            pc += 1
            pattern = frame.pop()
            target = frame.pop()
            frame.push(_checkmatch(target, pattern, flag))
        elif opcode == insns.THROW:
            throw_state = code[pc]
            pc += 1
            _throw(frame, throw_state, frame.pop())
        elif opcode == insns.LEAVE:
            return frame.pop()
        elif opcode == insns.SETN:
            n = code[pc]
            pc += 1
            at = frame.sp - 1 - n
            top = frame.sp - 1
            if at < 0:
                raise UnsupportedOperation('setn %d underflows the stack' % n)
            assert top >= 0
            frame.stack[at] = frame.stack[top]
        elif opcode == insns.TOPN:
            n = code[pc]
            pc += 1
            at = frame.sp - 1 - n
            if at < 0:
                raise UnsupportedOperation('topn %d underflows the stack' % n)
            frame.push(frame.stack[at])
        elif opcode == insns.DUPN:
            n = code[pc]
            pc += 1
            _dupn(frame, n)
        elif opcode == insns.ADJUSTSTACK:
            n = code[pc]
            pc += 1
            _adjuststack(frame, n)
        elif opcode == insns.OPT_REVERSE:
            n = code[pc]
            pc += 1
            _reverse(frame, n)
        elif opcode == insns.NEWARRAY:
            n = code[pc]
            pc += 1
            frame.push(_newarray(frame, n))
        elif opcode == insns.DUPARRAY:
            idx = code[pc]
            pc += 1
            # The literal in the pool is shared; every evaluation gets a copy.
            frame.push(rubycall.ary_resurrect(iseq.consts[idx]))
        elif opcode == insns.NEWHASH:
            n = code[pc]
            pc += 1
            frame.push(_newhash(frame, n))
        elif opcode == insns.DUPHASH:
            idx = code[pc]
            pc += 1
            frame.push(rubycall.hash_resurrect(iseq.consts[idx]))
        elif opcode == insns.SPLATARRAY:
            idx = code[pc]
            pc += 1
            flag = value.is_true(iseq.consts[idx])
            frame.push(rubycall.splat_array(frame.pop(), flag))
        elif opcode == insns.OPT_AND:
            b = frame.pop()
            a = frame.pop()
            v = helpers.and_(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.AND))
        elif opcode == insns.OPT_OR:
            b = frame.pop()
            a = frame.pop()
            v = helpers.or_(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.OR))
        elif opcode == insns.NEWRANGE:
            flag = code[pc]
            pc += 1
            high = frame.pop()
            low = frame.pop()
            frame.push(rubycall.range_new(low, high, flag))
        elif opcode == insns.GETGLOBAL:
            mid = code[pc]
            pc += 1
            frame.push(rubycall.gvar_get(mid))
        elif opcode == insns.SETGLOBAL:
            mid = code[pc]
            pc += 1
            rubycall.gvar_set(mid, frame.pop())
        elif opcode == insns.OPT_AREF:
            idx = frame.pop()
            recv = frame.pop()
            v = helpers.aref(recv, idx)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, recv, idx, helpers.AREF))
        elif opcode == insns.OPT_ASET:
            val = frame.pop()
            idx = frame.pop()
            recv = frame.pop()
            v = helpers.aset(recv, idx, val)
            if v == value.Q_UNDEF:
                frame.push(recv)
                frame.push(idx)
                frame.push(val)
                v = _opt_send(frame, helpers.ASET, 2)
            frame.push(v)
        elif opcode == insns.OPT_LENGTH:
            recv = frame.pop()
            v = helpers.length(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.LENGTH))
        elif opcode == insns.OPT_SIZE:
            recv = frame.pop()
            v = helpers.size(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.SIZE))
        elif opcode == insns.OPT_EMPTY_P:
            recv = frame.pop()
            v = helpers.empty_p(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.EMPTY_P))
        elif opcode == insns.OPT_NOT:
            frame.push(helpers.opt_not(frame.pop()))
        elif opcode == insns.OPT_LTLT:
            b = frame.pop()
            a = frame.pop()
            frame.push(_binop(frame, a, b, helpers.LTLT))
        else:
            raise UnsupportedOperation('unknown opcode %d' % opcode)


def run(iseq):
    debug.dump_iseq(iseq)
    ret = execute(iseq, Frame(iseq, boot.top_self()))
    debug.summary()
    return ret


def run_in_cruby():
    """The whole script, handed back because some ISeq in it is one RPyYARV
    cannot represent. Cleans up too, so its answer is the exit status."""
    return boot.run_node()
