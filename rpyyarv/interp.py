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
                   PENDING_RAISE)
from iseq import CATCH_ENSURE, CATCH_RESCUE, NO_BLOCK_ISEQ
from rlib import (JitDriver, always_inline, dont_look_inside, promote,
                  unroll_safe)

TO_S = symbols.intern('to_s')
DUP = symbols.intern('dup')


def define_method(frame, mid, w_iseq):
    """A def in a class body lands on it; a toplevel def is private on Object."""
    klass = frame.cref
    if klass == 0:
        dispatch.define(value.core_class(value.C_OBJECT), mid, w_iseq, True)
    else:
        dispatch.define(klass, mid, w_iseq, False)


@unroll_safe
def invoke(frame, w_ci, w_block=None):
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
        callee_iseq = entry.w_iseq

    if callee_iseq is not None:
        if w_block is None:
            return _enter(frame, entry, recv, recv_at, argc, w_ci.mid, None)
        try:
            return _enter(frame, entry, recv, recv_at, argc, w_ci.mid,
                          w_block)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value

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
        return _call_with_block(recv, w_ci.mid, args, w_block)
    if not debug.state.enabled:
        return rubycall.call(recv, w_ci.mid, args)
    debug.trace_enter(w_ci.mid, args)
    ret = rubycall.call(recv, w_ci.mid, args)
    debug.trace_leave(w_ci.mid, ret)
    return ret


@unroll_safe
def _enter(frame, entry, recv, recv_at, argc, mid, w_block=None):
    """Move argc arguments into a fresh frame and run it; also invokesuper."""
    callee_iseq = entry.w_iseq
    if not callee_iseq.simple_params:
        raise UnsupportedOperation(
            "method '%s' has parameters RPyYARV does not support"
            % symbols.name_of(mid))
    if argc != callee_iseq.nparams:
        raise UnsupportedOperation(
            "wrong number of arguments to '%s' (given %d, expected %d)"
            % (symbols.name_of(mid), argc, callee_iseq.nparams))
    callee = Frame(callee_iseq, recv, 0, entry)
    callee.block = w_block
    i = 0
    while i < argc:
        callee.locals[i] = frame.stack[recv_at + 1 + i]
        i += 1
    _drop(frame, recv_at)
    if not debug.state.enabled:
        return execute(callee_iseq, callee)
    args = []
    i = 0
    while i < argc:
        args.append(callee.locals[i])
        i += 1
    debug.trace_enter(mid, args)
    ret = execute(callee_iseq, callee)
    debug.trace_leave(mid, ret)
    return ret


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
        return rubycall.call(recv, w_ci.mid, args)
    old = _sym_mid(frame.stack[recv_at + 3])
    entry = dispatch.own_lookup(cbase, old)
    dispatch.undefine(cbase, name)
    if entry is not None:
        # An RPyYARV method: the alias is a second name for the same ISeq.
        dispatch.define(cbase, name, entry.w_iseq, entry.private)
        _drop(frame, recv_at)
        return value.Q_NIL
    args = [cbase, frame.stack[recv_at + 2], frame.stack[recv_at + 3]]
    _drop(frame, recv_at)
    return rubycall.call(recv, w_ci.mid, args)


@dont_look_inside
def _sym_mid(v):
    if not boot.is_symbol(v):
        raise UnsupportedOperation('alias or undef names something '
                                   'that is not a Symbol')
    return symbols.intern(boot.sym_of(v))


class _Blocks(object):
    """Blocks C refers to, by index only. One is alive exactly for the extent
    of its rb_block_call, so a stack suffices."""
    def __init__(self):
        self.stack = []
        self.error = None       # an RPython error the callback could not raise
        self.exc = None         # likewise, a Ruby exception


blocks = _Blocks()


def block_callback(handle, argc, argv):
    """Called from C, inside rb_block_call. No RPython exception may escape
    into libruby, so a failure is re-raised once the call has returned."""
    if blocks.error is not None or blocks.exc is not None:
        return boot.as_value(value.Q_NIL)
    w_block = blocks.stack[handle]
    args = boot.read_values(argv, argc)
    try:
        return boot.as_value(call_block(w_block, args))
    except RubyException, e:
        # Held: the RPython field it waits in is not something CRuby scans.
        gcroots.hold(e.value)
        blocks.exc = e
        return boot.as_value(value.Q_NIL)
    except block_mod.BlockBreak:
        # Unwinding would have to longjmp out of rb_block_call's frames.
        blocks.error = UnsupportedOperation(
            'break out of a block passed to a CRuby method is not supported')
        return boot.as_value(value.Q_NIL)
    except RPyYarvError, e:
        blocks.error = e
        return boot.as_value(value.Q_NIL)


@dont_look_inside
def _call_with_block(recv, mid, args, w_block):
    blocks.stack.append(w_block)
    try:
        ret = rubycall.call_with_block(recv, mid, args,
                                       len(blocks.stack) - 1)
    finally:
        blocks.stack.pop()
    exc = blocks.exc
    if exc is not None:
        blocks.exc = None
        gcroots.release(exc.value)
        raise exc
    err = blocks.error
    if err is not None:
        blocks.error = None
        raise err
    return ret


@unroll_safe
def call_block(w_block, args):
    """Run a block's ISeq in a frame whose locals chain to the defining one."""
    b_iseq = w_block.w_iseq
    outer = w_block.frame
    callee = Frame(b_iseq, outer.self_val, outer.cref, outer.entry)
    callee.defining_frame = outer
    callee.block = w_block.outer
    callee.own_block = w_block
    n = len(args)
    if n > b_iseq.nparams:
        n = b_iseq.nparams
    i = 0
    while i < n:
        callee.locals[i] = args[i]
        i += 1
    try:
        return execute(b_iseq, callee)
    except block_mod.BlockNext, e:
        return e.value


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
    def __init__(self, kind, value, w_block=None, name='raise'):
        self.kind = kind
        self.value = value
        self.w_block = w_block
        self.name = name


def _rethrow(throw):
    if throw.kind == PENDING_RAISE:
        raise RubyException(throw.value, throw.name)
    if throw.kind == PENDING_BREAK:
        raise block_mod.BlockBreak(throw.w_block, throw.value)
    raise block_mod.BlockNext(throw.value)


def _throw(frame, throw_state, v):
    tag = throw_state & optable.TAG_MASK
    if tag == optable.TAG_NEXT:
        raise block_mod.BlockNext(v)
    if tag == optable.TAG_BREAK:
        w_block = frame.own_block
        if w_block is None:
            raise UnsupportedOperation('break outside a block')
        raise block_mod.BlockBreak(w_block, v)
    if tag == optable.TAG_NONE:
        # vm_throw_continue: re-raise what this catch ISeq runs under.
        if frame.pending_kind == PENDING_NONE:
            raise UnsupportedOperation(
                'throw 0 outside a rescue or ensure body')
        _rethrow(Throw(frame.pending_kind, frame.pending_value,
                       frame.pending_block))
    if tag == optable.TAG_RETRY:
        raise UnsupportedOperation('retry is not supported')
    raise UnsupportedOperation(
        'throw with tag %d (return/redo) is not supported' % tag)


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
    """The cref's constant base. TODO: a nested cref chain, once modules land."""
    if frame.cref != 0:
        return frame.cref
    return value.core_class(value.C_OBJECT)


def _defineclass(mid, w_body, cbase, super_v):
    klass = dispatch.define_class(cbase, mid, super_v)
    return execute(w_body, Frame(w_body, klass, klass))


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


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'],
                      get_printable_location=get_printable_location)


def _epc(iseq, pc):
    """Catch-table ranges are against the pc *after* the raising instruction."""
    return pc + 1 + optable.NUM_OPERANDS[iseq.code[pc]]


def execute(iseq, frame):
    """Two shapes on purpose: the handler shape below stops the JIT inlining
    the call, so an ISeq with no catch table keeps a plain tail call instead.
    iseq is green, so the branch folds away."""
    if len(iseq.catches) == 0:
        gcroots.push_frame(frame)
        try:
            return _execute(iseq, frame, 0)
        finally:
            gcroots.pop_frame(frame)
    return _execute_guarded(iseq, frame)


def _execute_guarded(iseq, frame):
    gcroots.push_frame(frame)
    try:
        pc = 0
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
            frame.push(helpers.add(a, b))
        elif opcode == insns.OPT_MINUS:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.sub(a, b))
        elif opcode == insns.OPT_MULT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.mul(a, b))
        elif opcode == insns.OPT_LT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.lt(a, b))
        elif opcode == insns.OPT_GT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.gt(a, b))
        elif opcode == insns.OPT_LE:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.le(a, b))
        elif opcode == insns.OPT_GE:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.ge(a, b))
        elif opcode == insns.OPT_EQ:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.eq(a, b))
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
            frame.push(helpers.div(a, b))
        elif opcode == insns.OPT_MOD:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.mod(a, b))
        elif opcode == insns.OPT_NEQ:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.neq(a, b))
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
            frame.push(helpers.and_(a, b))
        elif opcode == insns.OPT_OR:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.or_(a, b))
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
            frame.push(helpers.aref(recv, idx))
        elif opcode == insns.OPT_ASET:
            val = frame.pop()
            idx = frame.pop()
            recv = frame.pop()
            frame.push(helpers.aset(recv, idx, val))
        elif opcode == insns.OPT_LENGTH:
            frame.push(helpers.length(frame.pop()))
        elif opcode == insns.OPT_SIZE:
            frame.push(helpers.size(frame.pop()))
        elif opcode == insns.OPT_EMPTY_P:
            frame.push(helpers.empty_p(frame.pop()))
        elif opcode == insns.OPT_NOT:
            frame.push(helpers.opt_not(frame.pop()))
        elif opcode == insns.OPT_LTLT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.ltlt(a, b))
        else:
            raise UnsupportedOperation('unknown opcode %d' % opcode)


def run(iseq):
    debug.dump_iseq(iseq)
    ret = execute(iseq, Frame(iseq, boot.top_self()))
    debug.summary()
    return ret
