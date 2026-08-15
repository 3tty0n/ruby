import os

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import dispatch
from rpyyarv import gcroots
from rpyyarv import helpers
from rpyyarv import insns
from rpyyarv import optable
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RPyYarvError, RubyException, UnsupportedOperation
from rpyyarv.frame import (Frame, PENDING_BREAK, PENDING_NEXT, PENDING_NONE,
                   PENDING_RAISE, PENDING_RETRY, PENDING_RETURN)
from rpyyarv.iseq import (CATCH_ENSURE, CATCH_RESCUE, CATCH_RETRY,
                          NO_BLOCK_ISEQ, W_CallInfo)
from rpyyarv.rlib import (JitDriver, StackOverflow, always_inline, check_stack_overflow,
                  dont_look_inside, on_foreign_stack, promote, raw_word, set_user_param,
                  unchecked_stack_start, unchecked_stack_stop, unroll_safe)

TO_S = symbols.intern('to_s')
DUP = symbols.intern('dup')
EVAL = symbols.intern('eval')
# The empty leading segment the loader puts in a `::Foo` constant path.
ROOT_CBASE = symbols.intern('')

# Prebuilt, so len() of it folds to 0 wherever a call passes no keywords.
NO_KEYWORDS = []


class Cref(object):
    """One lexical scope, chained as CRuby's rb_cref_t is; klass 0 is the toplevel Object."""
    _immutable_fields_ = ['klass', 'outer', 'by_eval', 'const_base']

    def __init__(self, klass, outer, by_eval=False):
        self.klass = klass
        self.outer = outer
        # CREF_PUSHED_BY_EVAL: a `def` lands on this class, but a constant lookup steps over it.
        self.by_eval = by_eval
        # Resolved once here, not walked per lookup: _const_base is on the hot path of every constant read.
        if by_eval and outer is not None:
            self.const_base = outer.const_base
        else:
            self.const_base = klass
        # klass -> Cref, so re-running a class body reuses the node a const site's guard holds.
        self.inner = {}
        self.eval_inner = {}


TOP_CREF = Cref(0, None)


def _push_cref(outer, klass, by_eval=False):
    table = outer.eval_inner if by_eval else outer.inner
    node = table.get(klass, None)
    if node is None:
        dispatch.root_base(klass)
        node = Cref(klass, outer, by_eval)
        table[klass] = node
    return node


def _cref_of(frame):
    """The lexical scope chain a constant resolves against; a method frame carries none of its own, so its entry's stands in."""
    c = frame.cref
    if c is None:
        entry = frame.entry
        if entry is not None:
            c = entry.lexical
    if c is None:
        return TOP_CREF
    return c


def define_method(frame, mid, w_iseq):
    """A def in a class body lands on it; a toplevel def is private on Object."""
    node = frame.cref
    if node is None:
        dispatch.define(value.core_class(value.C_OBJECT), mid, w_iseq, True,
                        0, _cref_of(frame))
    elif frame.module_func:
        dispatch.define(node.klass, mid, w_iseq, True, node.klass, node)
        dispatch.define_singleton(node.klass, mid, w_iseq, node.klass, node)
    else:
        dispatch.define(node.klass, mid, w_iseq, False, node.klass, node)


@unroll_safe
def invoke(frame, w_ci, w_block=None):
    if w_ci.blockarg:
        # Read before the pop, so the frame keeps it marked while _block_from_value may allocate (vm_args.c:1119).
        top = frame.sp - 1
        if top < 0:
            raise UnsupportedOperation(
                "call to '%s' passes a &block the stack does not hold"
                % symbols.name_of(w_ci.mid))
        w_block = _block_from_value(frame.block, frame.stack[top])
        frame.pop()
    # A `send` rewrites these three; the callinfo keeps the rest of the site.
    mid = w_ci.mid
    argc = w_ci.argc
    fcall = w_ci.fcall
    if mid == rubycall.REQUIRE_RELATIVE:
        # Green, so this store is only in the trace of a site that really is one.
        rubycall.relative.path = frame.w_iseq.path
    recv_at = frame.sp - argc - 1
    if recv_at < 0:
        raise UnsupportedOperation(
            "call to '%s' with %d argument(s) underflows the stack"
            % (symbols.name_of(mid), argc))
    if not w_ci.simple:
        if len(w_ci.kw_names) == 0 and not w_ci.kw_splat and not w_ci.splat:
            raise UnsupportedOperation(
                "call to '%s' passes arguments RPyYARV does not support"
                % symbols.name_of(mid))
        return _kw_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall)

    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    # Promoted: the guard on the class word is the inline cache, and the lookup below folds away behind it.
    klass = promote(value.class_of(recv))
    while mid == SEND or mid == SEND2:
        target = _send_target(frame, klass, mid, argc, recv_at)
        if target == rubycall.NO_MID:
            break
        _shift_off(frame, recv_at)
        argc -= 1
        mid = target
        fcall = True
    entry = dispatch.lookup(klass, mid)
    callee_iseq = None
    if entry is not None and (fcall or not entry.private):
        if entry.kind != dispatch.KIND_ISEQ:
            return _attr_send(frame, entry, recv, recv_at, argc)
        callee_iseq = entry.w_iseq

    if callee_iseq is not None:
        if w_block is None or w_ci.blockarg:
            # A break unwinds to the send the block was *written* at, not one that passed it on.
            return _enter(frame, entry, recv, recv_at, argc, mid, w_block)
        try:
            return _enter(frame, entry, recv, recv_at, argc, mid,
                          w_block)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value

    if mid == ITSELF and argc == 0 and dispatch.owner_of(klass, ITSELF) == \
            send_owners.kernel:
        _drop(frame, recv_at)
        debug.count_native()
        return recv
    if mid == GETBYTE and argc == 1 and \
            dispatch.owner_of(klass, GETBYTE) == send_owners.string_getbyte:
        v = boot.str_getbyte(recv, frame.stack[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if mid == SETBYTE and argc == 2 and \
            dispatch.owner_of(klass, SETBYTE) == send_owners.string_setbyte:
        v = boot.str_setbyte(recv, frame.stack[recv_at + 1],
                             frame.stack[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if mid == SLICE and argc == 2 and entry is None and \
            value.is_plain_array(recv) and \
            dispatch.owner_of(klass, SLICE) == value.core_class(value.C_ARRAY):
        beg = frame.stack[recv_at + 1]
        length = frame.stack[recv_at + 2]
        if value.is_fixnum(beg) and value.is_fixnum(length):
            ibeg = value.fix2int(beg)
            if ibeg < 0:
                ibeg += value.ary_len(recv)
            v = value.Q_NIL if ibeg < 0 else \
                boot.ary_subseq(recv, ibeg, value.fix2int(length))
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc <= 1:
        # A send an opt_* instruction would have caught if YARV had one for it.
        if argc == 1:
            v = _native_binop(recv, frame.stack[recv_at + 1], mid)
        else:
            v = helpers.zero_arg(recv, mid)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 \
            and (mid == helpers.LT or mid == helpers.GT
                 or mid == helpers.LE or mid == helpers.GE) \
            and send_owners.comparable != 0 \
            and dispatch.owner_of(klass, mid) == send_owners.comparable:
        return _comparable_op(frame, mid, recv_at)
    if entry is None and argc == 1 and mid == ENC_FIND \
            and encodings.value != 0 and recv == encodings.value:
        v = _encoding_find(frame, recv, recv_at)
        if v != value.Q_UNDEF:
            return v
    if entry is None and argc == 2 and mid == helpers.TR:
        v = helpers.str_tr(recv, frame.stack[recv_at + 1],
                           frame.stack[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and mid == helpers.ASET:
        v = helpers.hash_aset(recv, frame.stack[recv_at + 1],
                              frame.stack[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and mid == EVAL and fcall \
            and (argc == 1 or (argc == 3 \
                              and frame.stack[recv_at + 2] == value.Q_NIL)):
        v = _eval_rpy(frame, klass, recv, frame.stack[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and (mid == CLASS_EVAL or mid == MODULE_EVAL) and \
            w_block is None and argc >= 1 and argc <= 3 and \
            (dispatch.is_known_class(recv) or dispatch.is_known_module(recv)):
        v = _module_eval_rpy(frame, recv, frame.stack[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if w_block is not None and entry is None and argc == 0 \
            and not w_ci.blockarg \
            and (mid == CLASS_EVAL or mid == MODULE_EVAL) \
            and w_block.kind == block_mod.KIND_ISEQ \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)) \
            and dispatch.owner_of(klass, mid) == \
            value.core_class(value.C_MODULE):
        return _module_eval_block(frame, recv, recv_at, w_block)
    if _is_attr_mid(mid) and argc > 0 and not value.is_immediate(recv) \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)):
        return _define_attrs(frame, mid, recv, recv_at, argc)
    if mid == INITIALIZE and argc == 0 and entry is None and w_block is None \
            and helpers.basic_initialize(klass):
        # rb_obj_dummy_initialize: no argument, no effect, nil (object.c:118).
        _drop(frame, recv_at)
        debug.count_native()
        return value.Q_NIL
    if mid == BLOCK_GIVEN and fcall and argc == 0:
        # rb_f_block_given_p reads the *caller's* frame (vm.c:1862); through rb_funcallv it would find a CRuby one.
        _drop(frame, recv_at)
        return value.newbool(frame.block is not None)
    if (mid == METHOD_UNDERSCORE or mid == CALLEE_UNDERSCORE) \
            and fcall and argc == 0 and entry is None:
        # rb_f_method_name reads the running CRuby frame, and RPyYARV pushes none; the frame's own entry is what it would have named.
        _drop(frame, recv_at)
        debug.count_native()
        return _running_method(frame)
    if mid == BACKTRACE_PRIM and fcall and argc == 0:
        _drop(frame, recv_at)
        debug.count_native()
        return _backtrace()
    if mid == HASH_PAIRS_PRIM and fcall and argc == 1 \
            and boot.is_hash(frame.stack[recv_at + 1]):
        v = boot.hash_pairs(frame.stack[recv_at + 1])
        _drop(frame, recv_at)
        debug.count_native()
        return v
    if mid == DIR_UNDERSCORE and fcall and argc == 0:
        # Likewise f_dir: the running file is this frame's ISeq, not any CRuby frame's.
        v = _dir_of(frame)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            return v
    if mid == NEW and helpers.ary_new_pristine(promote(recv)):
        if w_block is None:
            size = frame.stack[recv_at + 1] if argc >= 1 else value.Q_NIL
            fill = frame.stack[recv_at + 2] if argc == 2 else value.Q_NIL
            v = _array_new(size, fill, argc)
            if v != value.Q_UNDEF:
                _drop(frame, recv_at)
        else:
            v = _array_new_block(frame, recv_at, argc, w_block)
        if v != value.Q_UNDEF:
            debug.count_native()
            return v
    if w_block is not None and mid == NEW \
            and dispatch.is_known_class(recv):
        entry = dispatch.lookup(promote(recv), INITIALIZE)
        if entry is not None and entry.kind == dispatch.KIND_ISEQ:
            return _new_with_block(frame, entry, recv, recv_at, argc, w_block)
    if w_block is not None and entry is None and argc == 0 \
            and value.is_plain_array(recv) and value.ary_len(recv) == 0 \
            and dispatch.owner_of(klass, mid) == value.core_class(value.C_ARRAY):
        if mid == REVERSE_EACH:
            _drop(frame, recv_at)
            return recv
        if mid == INDEX:
            _drop(frame, recv_at)
            return value.Q_NIL
    if w_block is not None and mid == EACH_SLICE and argc == 1 and \
            entry is None and value.is_plain_array(recv) and \
            dispatch.owner_of(klass, EACH_SLICE) == \
            send_owners.array_each_slice:
        size = frame.stack[recv_at + 1]
        if value.is_fixnum(size) and value.fix2int(size) > 0:
            _drop(frame, recv_at)
            try:
                return _array_each_slice(recv, value.fix2int(size), w_block)
            except block_mod.BlockBreak, e:
                if e.w_block is not w_block:
                    raise
                return e.value
    if entry is None and w_block is None and not value.is_immediate(recv) \
            and (raw_word(recv, value.FLAGS_WORD) & value.T_MASK) == \
            value.T_STRUCT:
        writer = symbols.name_of(mid).endswith('=')
        if (argc == 1 and writer) or (argc == 0 and not writer):
            index = dispatch.struct_member_index(klass, mid)
            if index >= 0:
                if argc == 0:
                    out = boot.struct_get(recv, index)
                    if out != value.Q_UNDEF:
                        _drop(frame, recv_at)
                        return out
                elif (raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE) == 0:
                    out = frame.stack[recv_at + 1]
                    boot.struct_set(recv, index, out)
                    _drop(frame, recv_at)
                    return out
    if proxy.value != 0 and recv == proxy.value:
        return _block_send(frame, mid, recv_at, argc, frame.block)
    if len(blocks.by_proc) > 0 \
            and (_is_proxy_call(mid) or mid == ARITY or mid == LAMBDA_P) \
            and recv in blocks.by_proc:
        # A Proc RPyYARV made: run its block here instead of out to CRuby and back through the block callback.
        return _block_send(frame, mid, recv_at, argc, blocks.by_proc[recv])
    if w_block is not None and entry is None \
            and (mid == INSTANCE_EVAL or mid == INSTANCE_EXEC) \
            and w_block.kind == block_mod.KIND_ISEQ \
            and (mid == INSTANCE_EXEC or argc == 0) \
            and helpers.instance_eval_pristine(mid) \
            and dispatch.owner_of(klass, mid) \
            == value.core_class(value.C_BASIC_OBJECT):
        return _instance_eval(frame, mid, recv, recv_at, argc, w_block)
    if w_block is not None and entry is None and fcall and argc == 0 \
            and not w_ci.blockarg \
            and (mid == CORE_LAMBDA or mid == KERNEL_PROC) \
            and w_block.kind == block_mod.KIND_ISEQ \
            and helpers.modules.kernel != 0 \
            and dispatch.owner_of(klass, mid) == helpers.modules.kernel:
        # Kernel#lambda / Kernel#proc with a literal block: through rb_funcall_with_block the Proc would wrap a transient handle that dies with the call.
        _drop(frame, recv_at)
        debug.count_native()
        if mid == CORE_LAMBDA:
            return _to_proc(block_mod.W_Block(
                w_block.w_iseq, w_block.frame, w_block.outer, is_lambda=True))
        return _to_proc(w_block)
    if mid == MODULE_FUNCTION and fcall \
            and (_in_body_of(frame, recv)
                 or (argc > 0 and dispatch.is_known_module(recv))):
        # With names it also works from a method body (fileutils.rb's private_module_function); the registry must mirror the singleton copies.
        return _module_function(frame, recv, recv_at, argc)
    if mid == PRIVATE_CLASS_METHOD and argc > 0 \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)):
        return _private_class_method(frame, recv, recv_at, argc)
    if mid == CORE_ALIAS or mid == CORE_UNDEF:
        return _core_method(frame, mid, recv, recv_at, argc)
    if mid == ALIAS_METHOD and argc == 2 and entry is None \
            and not value.is_immediate(recv) and boot.is_class(recv) \
            and dispatch.owner_of(klass, mid) == \
            value.core_class(value.C_MODULE):
        return _alias_method(frame, recv, recv_at)
    if vm_core.value != 0 and recv == vm_core.value \
            and mid != HASH_MERGE_PTR and mid != HASH_MERGE_KWD:
        if mid == CORE_GVAR_ALIAS and argc == 2:
            boot.alias_variable(frame.stack[recv_at + 1],
                                frame.stack[recv_at + 2])
            _drop(frame, recv_at)
            debug.count_native()
            return value.Q_NIL
        if mid == CORE_LAMBDA and w_block is not None \
                and w_block.kind == block_mod.KIND_ISEQ:
            # `->`: the same block re-tagged as a lambda, over a persistent handle the mark hook keeps deep-marked.
            _drop(frame, recv_at)
            debug.count_native()
            return _to_proc(block_mod.W_Block(
                w_block.w_iseq, w_block.frame, w_block.outer,
                is_lambda=True))
        raise UnsupportedOperation(
            "RubyVM::FrozenCore#%s is not supported"
            % symbols.name_of(mid))

    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    if w_block is not None:
        if w_ci.blockarg:
            return _call_with_block(recv, mid, args, w_block)
        try:
            return _call_with_block(recv, mid, args, w_block)
        except block_mod.BlockBreak, e:
            # As above: only the send the block was written at catches it.
            if e.w_block is not w_block:
                raise
            return e.value
    # An entry survives here only as private to a receiverless call, which rb_funcallv reaches anyway (CALL_FCALL).
    public_only = entry is not None and not fcall
    if not debug.state.enabled:
        ret = rubycall.call(recv, mid, args, public_only)
        # The callee may have run a Proc of ours, which cannot raise through libruby's frames and parked instead.
        _check_block_error()
        return ret
    debug.trace_enter(mid, args)
    ret = rubycall.call(recv, mid, args, public_only)
    _check_block_error()
    debug.trace_leave(mid, ret)
    return ret


# Above this the block form goes back to CRuby: the loop below is traced, not a jitdriver, so a long one would blow the trace.
ARY_NEW_BLOCK_MAX = 64

# rb_ary_resize is the only public way to set the length, and it nil-fills; above this that second pass costs more than the dispatch a native fill saves.
ARY_NEW_FILL_MAX = 128


@dont_look_inside
def _array_new(size, fill, argc):
    """rb_ary_s_new for a direct Array (array.c:1071); Qundef for every argument shape rb_ary_initialize treats specially. Takes the values, not the frame, so it never escapes the virtualizable."""
    # Left out of line on purpose: inlining these paths grew cd's and havlak's traces ~5%, and rb_ary_new is a call either way.
    if argc > 2:
        return value.Q_UNDEF
    if argc == 0:
        return rubycall.ary_new_capa(0)
    # FIXNUM_P, as rb_ary_s_new tests it: to_int, to_ary and a Bignum all take rb_ary_initialize's slow paths.
    if not value.is_fixnum(size):
        return value.Q_UNDEF
    n = value.fix2int(size)
    if n < 0:
        return value.Q_UNDEF
    if argc == 2 and n > ARY_NEW_FILL_MAX:
        return value.Q_UNDEF
    return rubycall.ary_new_filled(n, fill)


@unroll_safe
def _array_new_block(frame, recv_at, argc, w_block):
    """Traced through, unlike _array_new: a block reading an enclosing local forces the caller's virtualizable, which aborts the trace unless the whole fill is inlined."""
    # argc == 0 is rb_warning("given block not used") and argc == 2 "block supersedes default value argument".
    if argc != 1:
        return value.Q_UNDEF
    size = frame.stack[recv_at + 1]
    if not value.is_fixnum(size):
        return value.Q_UNDEF
    n = value.fix2int(size)
    if n < 0 or n > ARY_NEW_BLOCK_MAX:
        return value.Q_UNDEF
    ary = rubycall.ary_new_capa(n)
    # Into the receiver's slot, which the caller's frame marks: the block runs arbitrary Ruby and nothing else holds the array.
    frame.stack[recv_at] = ary
    i = 0
    while i < n:
        v = call_block(w_block, [value.int2fix(i)])
        # rb_ary_store, so a block that raises leaves the length CRuby would.
        rubycall.ary_store_fresh(ary, i, v)
        i += 1
    _drop(frame, recv_at)
    return ary


def _array_each_slice(ary, size, w_block):
    """Enumerable#each_slice for a plain Array, without one CRuby callback per slice."""
    at = 0
    while at < value.ary_len(ary):
        remaining = value.ary_len(ary) - at
        count = size if size < remaining else remaining
        part = boot.ary_subseq(ary, at, count)
        call_block(w_block, [part])
        at += count
    return ary


NEW = symbols.intern('new')
INITIALIZE = symbols.intern('initialize')
BLOCK_GIVEN = symbols.intern('block_given?')
DIR_UNDERSCORE = symbols.intern('__dir__')
BACKTRACE_PRIM = symbols.intern('__rpyyarv_backtrace__')
HASH_PAIRS_PRIM = symbols.intern('__rpyyarv_hash_pairs__')
METHOD_UNDERSCORE = symbols.intern('__method__')
CALLEE_UNDERSCORE = symbols.intern('__callee__')


# A deeper chain than this is a runaway; caller only ever reads the top anyway.
MAX_BACKTRACE = 4096
# What RubyVM::InstructionSequence.compile names a source with no file, which is how prelude.rb is built; its frames are RPyYARV's own and no caller ever wrote them.
COMPILED_PATH = '<compiled>'


def _running_method(frame):
    """__method__: the entry the innermost method frame runs under, walking out of the blocks written inside it; nil at the toplevel, as rb_f_method_name answers there."""
    f = frame
    n = 0
    while f is not None and n < MAX_SCOPES:
        entry = f.entry
        if entry is not None:
            return rubycall.sym_value(entry.mid)
        f = f.defining_frame
        n += 1
    return value.Q_NIL


@dont_look_inside
def _backtrace():
    """path, line and label of every live RPyYARV frame, innermost first, flattened into one Array; the prelude's Kernel#caller turns it into what CRuby answers. CRuby's own caller_locations sees none of these frames, since RPyYARV pushes no CRuby control frame."""
    ary = rubycall.ary_new([])
    # Held: the strings below allocate, and an RPython list is no GC root.
    gcroots.hold(ary)
    try:
        f = gcroots.state.top
        n = 0
        at = 0
        while f is not None and n < MAX_BACKTRACE:
            n += 1
            w_iseq = f.w_iseq
            path = w_iseq.path
            if path == COMPILED_PATH or path == '':
                f = f.prev_frame
                continue
            rubycall.ary_store(ary, at, boot.str_new(path))
            rubycall.ary_store(ary, at + 1,
                               value.int2fix(w_iseq.line_for(f.pc)))
            rubycall.ary_store(ary, at + 2, boot.str_new(w_iseq.name))
            at += 3
            f = f.prev_frame
    finally:
        gcroots.release(ary)
    return ary


@dont_look_inside
def _dir_of(frame):
    """__dir__ for the file this frame's ISeq came from; Qundef for an ISeq with no file, which goes back to CRuby."""
    path = frame.w_iseq.path
    if path == '' or path.startswith('<'):
        return value.Q_UNDEF
    return boot.dir_of(boot.str_new(path))
ITSELF = symbols.intern('itself')
REVERSE_EACH = symbols.intern('reverse_each')
EACH_SLICE = symbols.intern('each_slice')
INDEX = symbols.intern('index')
SUCC = symbols.intern('succ')
BUFFER = symbols.intern('buffer')
GETBYTE = symbols.intern('getbyte')
SETBYTE = symbols.intern('setbyte')

DEFINED_IVAR = 2
DEFINED_GVAR = 4
DEFINED_CVAR = 5
DEFINED_CONST = 6
DEFINED_METHOD = 7
DEFINED_YIELD = 8
DEFINED_FUNC = 16
DEFINED_CONST_FROM = 17
ATTR_READER = symbols.intern('attr_reader')
ATTR_WRITER = symbols.intern('attr_writer')
ATTR_ACCESSOR = symbols.intern('attr_accessor')


def _is_attr_mid(mid):
    return (mid == ATTR_READER or mid == ATTR_WRITER
            or mid == ATTR_ACCESSOR)


SEND = symbols.intern('send')
SEND2 = symbols.intern('__send__')
# opt_regexpmatch2 has no fast path here: it falls straight through to this send, which is where CRuby sets $~ for the getspecial that follows.
MATCH = symbols.intern('=~')


class _SendOwners(object):
    # Quasi-immutable: install() writes it once, before any Ruby code runs.
    _immutable_fields_ = ['kernel?', 'basic?', 'string_getbyte?',
                          'string_setbyte?', 'array_each_slice?',
                          'comparable?']

    def __init__(self):
        self.kernel = 0
        self.basic = 0
        self.eval = 0
        self.string_getbyte = 0
        self.string_setbyte = 0
        self.array_each_slice = 0
        self.comparable = 0


# Kernel#send and BasicObject#__send__, so a class that overrides either is seen.
send_owners = _SendOwners()


def _send_target(frame, klass, mid, argc, recv_at):
    if argc < 1:
        return rubycall.NO_MID
    return _send_target_of(klass, mid, frame.stack[recv_at + 1])


def _send_target_of(klass, mid, name):
    """vm_call_opt_send: the method a `send` names, or NO_MID when this is not a pristine send."""
    if mid == SEND:
        if not helpers.kernel_send_pristine():
            return rubycall.NO_MID
        owner = send_owners.kernel
    else:
        if not helpers.basic_send_pristine():
            return rubycall.NO_MID
        owner = send_owners.basic
    if owner == 0 or dispatch.owner_of(klass, mid) != owner:
        return rubycall.NO_MID
    if dispatch.lookup(klass, mid) is not None:
        return rubycall.NO_MID
    return _name_mid(name)


@dont_look_inside
def _name_mid(v):
    """rb_check_id of a send's first argument (vm_eval.c:1245); NO_MID leaves the send to CRuby, which raises for it."""
    if boot.is_symbol(v):
        return symbols.intern(boot.sym_of(v))
    if not value.is_immediate(v) and boot.is_string(v):
        return symbols.intern(boot.str_of(v))
    return rubycall.NO_MID


@unroll_safe
def _shift_off(frame, recv_at):
    """Drop a send's method-name argument, closing the gap the receiver sits under."""
    i = recv_at + 1
    assert i >= 0
    while i < frame.sp - 1:
        frame.stack[i] = frame.stack[i + 1]
        i += 1
    frame.pop()


def _native_binop(recv, arg, mid):
    """A one-argument send RPyYARV answers itself, or Qundef."""
    if mid == helpers.EQQ:
        v = helpers.int_eqq(recv, arg)
        if v != value.Q_UNDEF:
            return v
        v = helpers.sym_eqq(recv, arg)
        if v != value.Q_UNDEF:
            return v
        v = helpers.str_eqq(recv, arg)
        if v != value.Q_UNDEF:
            return v
        return helpers.mod_eqq(recv, arg)
    if mid == helpers.KIND_OF_P or mid == helpers.IS_A_P:
        return helpers.kind_of(recv, arg, mid)
    if mid == helpers.INSTANCE_OF_P:
        return helpers.instance_of(recv, arg)
    if mid == helpers.KEY_P or mid == helpers.HAS_KEY_P:
        return helpers.hash_key_p(recv, arg, mid)
    if mid == helpers.INCLUDE_P:
        return helpers.set_include(recv, arg)
    if mid == helpers.START_WITH_P:
        return helpers.str_start_with(recv, arg)
    if mid == helpers.XOR:
        return helpers.xor(recv, arg)
    if mid == helpers.RSHIFT:
        return helpers.rshift(recv, arg)
    if mid == helpers.LTLT:
        return helpers.lshift(recv, arg)
    if mid == helpers.CASECMP:
        return helpers.str_casecmp(recv, arg)
    if mid == helpers.INDEX_MID:
        return helpers.str_index(recv, arg)
    if mid == helpers.MATCH_P:
        return helpers.str_match_p(recv, arg)
    if mid == helpers.PUSH_MID:
        return helpers.ary_push_one(recv, arg)
    if mid == helpers.SPACESHIP:
        return helpers.spaceship(recv, arg)
    if mid == helpers.DIV_WORD:
        return helpers.int_div_word(recv, arg)
    if mid == helpers.AREF:
        v = helpers.hash_aref(recv, arg)
        if v != value.Q_UNDEF:
            return v
        v = helpers.int_bitref(recv, arg)
        if v != value.Q_UNDEF:
            return v
        return helpers.ary_sub_aref(recv, arg)
    if mid == helpers.SQRT:
        return helpers.math_sqrt(recv, arg)
    if mid == helpers.COS:
        return helpers.math_cos(recv, arg)
    if mid == helpers.POW:
        return helpers.flt_pow(recv, arg)
    if mid == helpers.RESPOND_TO_P:
        return helpers.responds_to(recv, arg)
    if (mid == helpers.EQ or mid == helpers.NEQ or mid == helpers.EQUAL_P) \
            and helpers.identity_send(recv, mid):
        same = recv == arg
        if mid == helpers.NEQ:
            same = not same
        return value.newbool(same)
    return value.Q_UNDEF


def _attr_send(frame, entry, recv, recv_at, argc):
    """An attr_* entry: the shape-guarded ivar access getinstancevariable compiles to, without a frame."""
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
def _define_attrs(frame, mid, klass, recv_at, argc):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    # First, so a name CRuby rejects raises before anything is registered.
    ret = rubycall.call(klass, mid, args)
    _install_attrs(klass, mid, args)
    return ret


@dont_look_inside
def _install_attrs(klass, mid, args):
    """attr_* still runs in CRuby, so its entries stay there for reflection and CRuby's callers; the registry gains native ones too."""
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


@dont_look_inside
def _eval_rpy(frame, klass, recv, source):
    """The two binding-free eval forms used by optcarrot's code generator."""
    if value.is_immediate(source) or not boot.is_string(source):
        return value.Q_UNDEF
    if dispatch.owner_of(klass, EVAL) != send_owners.eval:
        return value.Q_UNDEF
    name = boot.str_of(source)
    if name.startswith('def self.run'):
        from rpyyarv import bootiseq
        from rpyyarv import loader
        from rpyyarv import prelude
        w_iseq = loader.load_strict(bootiseq.load(prelude._compile(name)))
        return execute(w_iseq, Frame(w_iseq, recv, frame.cref, frame.entry))
    if len(name) == 0 or name[0] < 'A' or name[0] > 'Z':
        return value.Q_UNDEF
    i = 1
    while i < len(name):
        c = name[i]
        if not ((c >= 'A' and c <= 'Z') or (c >= 'a' and c <= 'z')
                or (c >= '0' and c <= '9') or c == '_'):
            return value.Q_UNDEF
        i += 1
    return _const_lexical(_cref_of(frame), symbols.intern(name))


@dont_look_inside
def _module_eval_rpy(frame, recv, source):
    """String class_eval/module_eval with the caller's lexical CREF preserved; a string RPyYARV cannot compile or load goes back to CRuby's module_eval."""
    if value.is_immediate(source) or not boot.is_string(source):
        return value.Q_UNDEF
    from rpyyarv import bootiseq
    from rpyyarv import loader
    from rpyyarv import prelude
    text = boot.str_of(source)
    try:
        result = loader.load(bootiseq.load(prelude._compile(text)))
    except RubyException:
        return value.Q_UNDEF
    except RPyYarvError:
        return value.Q_UNDEF
    if len(result.reasons) > 0:
        return value.Q_UNDEF
    cref = _push_cref(_cref_of(frame), recv, True)
    return execute(result.w_iseq, Frame(result.w_iseq, recv, cref,
                                        frame.entry))


def _new_with_block(frame, entry, klass, recv_at, argc, w_block):
    """`Klass.new { }` run here: through CRuby's Class#new, initialize would get a Proc over a block handle that dies when it returns."""
    obj = dispatch.alloc(klass)
    # Into the caller's marked slot, since _enter drops it only once the arguments are placed.
    frame.stack[recv_at] = obj
    _enter(frame, entry, obj, recv_at, argc, INITIALIZE, w_block)
    return obj


@unroll_safe
def _kw_splat_hash(frame, at):
    """vm_caller_setup_keyword_hash: anything but a Hash goes through to_hash first, so every reader below sees one; nil stands for no keywords at all."""
    # Restated so the codewriter sees the stack index as non-negative.
    assert at >= 0
    v = frame.stack[at]
    if v == value.Q_NIL or (not value.is_immediate(v) and _is_hash(v)):
        return
    frame.stack[at] = rubycall.to_hash_type(v)


@dont_look_inside
def _is_hash(v):
    return boot.is_hash(v)


@unroll_safe
def _kw_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall):
    """A send with literal keywords (VM_CALL_KWARG), whose values are the topmost arguments named by w_ci.kw_names, or with a **splat (VM_CALL_KW_SPLAT), whose one Hash is the topmost argument."""
    if w_ci.kw_splat:
        _kw_splat_hash(frame, recv_at + argc)
    if w_ci.splat:
        return _splat_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall)
    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    klass = promote(value.class_of(recv))
    # As in invoke(); the keywords stay the topmost arguments, so only the name below them is shifted off.
    while mid == SEND or mid == SEND2:
        target = _send_target(frame, klass, mid, argc - len(w_ci.kw_names),
                              recv_at)
        if target == rubycall.NO_MID:
            break
        _shift_off(frame, recv_at)
        argc -= 1
        mid = target
        fcall = True
    entry = dispatch.lookup(klass, mid)
    if entry is not None and (fcall or not entry.private):
        if entry.kind != dispatch.KIND_ISEQ:
            # An attr_* entry takes no keywords, so this only ever raises the arity error CRuby would.
            return _attr_send(frame, entry, recv, recv_at, argc)
        if w_block is None or w_ci.blockarg:
            return _enter(frame, entry, recv, recv_at, argc, mid,
                          w_block, w_ci.kw_names, w_ci.kw_splat)
        try:
            return _enter(frame, entry, recv, recv_at, argc, mid,
                          w_block, w_ci.kw_names, w_ci.kw_splat)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value
    # As in invoke(): a block RPyYARV holds runs here, so its keyword parameters do not have to survive a round trip through libruby.
    if proxy.value != 0 and recv == proxy.value:
        return _block_send(frame, mid, recv_at, argc, frame.block,
                           w_ci.kw_names, w_ci.kw_splat)
    if len(blocks.by_proc) > 0 and _is_proxy_call(mid) \
            and recv in blocks.by_proc:
        return _block_send(frame, mid, recv_at, argc, blocks.by_proc[recv],
                           w_ci.kw_names, w_ci.kw_splat)
    # Left in the marked frame until rb_hash_aset has copied each one, as _newhash does.
    kw_names = w_ci.kw_names
    nkw = len(kw_names)
    base = recv_at + 1
    n = argc - nkw
    # Restated so the codewriter sees every stack index as non-negative.
    assert base >= 0
    assert n >= 0
    args = []
    i = 0
    while i < n:
        args.append(frame.stack[base + i])
        i += 1
    pass_kw = True
    if w_ci.kw_splat:
        # `**{}` compiles to a putnil, which stands for no keywords at all.
        if n > 0 and args[n - 1] == value.Q_NIL:
            args.pop()
            pass_kw = False
    else:
        # Resolved before the Hash exists: rb_intern allocates, and only the frame keeps a VALUE marked, never an RPython list.
        rubycall.rid(mid)
        i = 0
        while i < nkw:
            rubycall.sym_value(kw_names[i])
            i += 1
        h = rubycall.hash_new(nkw)
        i = 0
        while i < nkw:
            rubycall.hash_aset(h, rubycall.sym_value(kw_names[i]),
                               frame.stack[base + n + i])
            i += 1
        args.append(h)
    _drop(frame, recv_at)
    if w_block is not None:
        if w_ci.blockarg:
            return _call_with_block(recv, mid, args, w_block, pass_kw)
        try:
            return _call_with_block(recv, mid, args, w_block, pass_kw)
        except block_mod.BlockBreak, e:
            # As in invoke(): only the send the block was written at catches it.
            if e.w_block is not w_block:
                raise
            return e.value
    public_only = entry is not None and not fcall
    if pass_kw:
        ret = rubycall.call_kw(recv, mid, args, public_only)
    else:
        ret = rubycall.call(recv, mid, args, public_only)
    _check_block_error()
    return ret


@dont_look_inside
def _ary_len(v):
    if value.is_immediate(v) or not boot.is_array(v):
        raise UnsupportedOperation('a *splat argument is not an Array')
    return boot.ary_len(v)


@dont_look_inside
def _ary_entry(ary, i):
    return boot.ary_entry(ary, i)


@unroll_safe
def _splat_trailing(frame, args, at, npos, trailing):
    i = 0
    while i < trailing:
        j = at + npos + i
        assert j >= 0
        args.append(frame.stack[j])
        i += 1
    return args


@unroll_safe
def _splat_args(frame, at, npos, trailing):
    """The arguments of a *splat call as a list: the Array is the last positional (the compiler pushed anything after it into the Array itself), and it stays on the frame's stack, which is what keeps its elements marked."""
    # Restated so the codewriter sees every stack index as non-negative.
    assert at >= 0
    args = []
    i = 0
    while i < npos - 1:
        j = at + i
        assert j >= 0
        args.append(frame.stack[j])
        i += 1
    splat_at = at + npos - 1
    assert splat_at >= 0
    ary = frame.stack[splat_at]
    if value.is_plain_array(ary):
        # Read in place, as opt_aref does: a call per element would force the virtualizable on every splat call.
        n = promote(value.ary_len(ary))
        i = 0
        while i < n:
            args.append(value.ary_at(ary, i))
            i += 1
        return _splat_trailing(frame, args, at, npos, trailing)
    # Promoted: the expansion's length is what makes args a fixed-size list the trace can keep virtual.
    n = promote(_ary_len(ary))
    i = 0
    while i < n:
        args.append(_ary_entry(ary, i))
        i += 1
    i = 0
    while i < trailing:
        j = at + npos + i
        assert j >= 0
        args.append(frame.stack[j])
        i += 1
    return args


@unroll_safe
def _splat_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall):
    """A call site with a *splat, whose expansion is a list: it may be longer than the stack the compiler sized this frame for."""
    kw_names = w_ci.kw_names
    nkw = len(kw_names)
    trailing = 1 if w_ci.kw_splat else nkw
    args = _splat_args(frame, recv_at + 1, argc - trailing, trailing)
    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    klass = promote(value.class_of(recv))
    while mid == SEND or mid == SEND2:
        if len(args) - trailing < 1:
            break
        target = _send_target_of(klass, mid, args[0])
        if target == rubycall.NO_MID:
            break
        args = args[1:]
        mid = target
        fcall = True
    entry = dispatch.lookup(klass, mid)
    if entry is not None and (fcall or not entry.private):
        if entry.kind != dispatch.KIND_ISEQ:
            return _attr_send_args(frame, entry, recv, recv_at, args)
        if w_block is None or w_ci.blockarg:
            return _enter_args(frame, entry, recv, recv_at, args, mid,
                               w_block, kw_names, w_ci.kw_splat)
        try:
            return _enter_args(frame, entry, recv, recv_at, args, mid,
                               w_block, kw_names, w_ci.kw_splat)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value
    if proxy.value != 0 and recv == proxy.value:
        _drop(frame, recv_at)
        return _block_send_args(mid, frame.block, args, kw_names,
                                w_ci.kw_splat)
    if len(blocks.by_proc) > 0 and _is_proxy_call(mid) \
            and recv in blocks.by_proc:
        w_proc = blocks.by_proc[recv]
        _drop(frame, recv_at)
        return _block_send_args(mid, w_proc, args, kw_names, w_ci.kw_splat)
    # Built while the arguments are still on the marked stack, as _kw_invoke does.
    pass_kw = w_ci.kw_splat or nkw > 0
    if w_ci.kw_splat:
        # `**{}` compiles to a putnil, which stands for no keywords at all.
        if len(args) > 0 and args[len(args) - 1] == value.Q_NIL:
            args.pop()
            pass_kw = False
    elif nkw > 0:
        rubycall.rid(mid)
        args = _kw_to_positional(args, kw_names)
    _drop(frame, recv_at)
    if w_block is not None:
        if w_ci.blockarg:
            return _call_with_block(recv, mid, args, w_block, pass_kw)
        try:
            return _call_with_block(recv, mid, args, w_block, pass_kw)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value
    public_only = entry is not None and not fcall
    if pass_kw:
        ret = rubycall.call_kw(recv, mid, args, public_only)
    else:
        ret = rubycall.call(recv, mid, args, public_only)
    _check_block_error()
    return ret


def _attr_send_args(frame, entry, recv, recv_at, args):
    """_attr_send for a *splat call, whose arguments are already a list."""
    argc = len(args)
    if entry.kind == dispatch.KIND_ATTR_READER:
        if argc != 0:
            _arity_error(argc, 0, 0)
        _drop(frame, recv_at)
        debug.count_native()
        return dispatch.ivar_get(recv, entry.ivar)
    if argc != 1:
        _arity_error(argc, 1, 1)
    v = args[0]
    dispatch.ivar_set(recv, entry.ivar, v)
    _drop(frame, recv_at)
    debug.count_native()
    return v


@unroll_safe
def _enter_args(frame, entry, recv, recv_at, args, mid, w_block=None,
                kw_names=NO_KEYWORDS, kw_splat=False):
    """_enter for a *splat call; the caller's stack still holds the Array the arguments came out of until the drop below."""
    callee_iseq = entry.w_iseq
    callee = Frame(callee_iseq, recv, None, entry)
    callee.block = w_block
    pc = 0
    argc = len(args)
    if callee_iseq.simple_params and len(kw_names) == 0 and not kw_splat:
        if argc != callee_iseq.nparams:
            _arity_error(argc, callee_iseq.nparams, callee_iseq.nparams)
        i = 0
        while i < argc:
            callee.local_set(i, args[i])
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        pc = setup_params(callee_iseq, callee, args, False, kw_names,
                          kw_splat)
    _drop(frame, recv_at)
    debug.count_native()
    if not debug.state.enabled:
        return execute(callee_iseq, callee, pc)
    debug.trace_enter(mid, args)
    ret = execute(callee_iseq, callee, pc)
    debug.trace_leave(mid, ret)
    return ret


@unroll_safe
def _enter(frame, entry, recv, recv_at, argc, mid, w_block=None,
           kw_names=NO_KEYWORDS, kw_splat=False):
    """Move argc arguments into a fresh frame and run it; also invokesuper."""
    callee_iseq = entry.w_iseq
    callee = Frame(callee_iseq, recv, None, entry)
    callee.block = w_block
    pc = 0
    if callee_iseq.simple_params and len(kw_names) == 0 and not kw_splat:
        if argc != callee_iseq.nparams:
            _arity_error(argc, callee_iseq.nparams, callee_iseq.nparams)
        i = 0
        while i < argc:
            callee.local_set(i, frame.stack[recv_at + 1 + i])
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        # Copied out first: the codewriter refuses a virtualizable array passed on, and the caller's frame keeps them marked.
        given = [0] * argc
        i = 0
        while i < argc:
            given[i] = frame.stack[recv_at + 1 + i]
            i += 1
        pc = setup_params(callee_iseq, callee, given, False, kw_names,
                          kw_splat)
    _drop(frame, recv_at)
    debug.count_native()
    if not debug.state.enabled:
        return execute(callee_iseq, callee, pc)
    args = []
    i = 0
    while i < argc:
        args.append(callee.local_get(i))
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
def setup_params(w_iseq, callee, args, is_block, kw_names=NO_KEYWORDS,
                 kw_splat=False):
    """vm_args.c setup_parameters_complex; answers the pc the opt table names (vm_args.c:906)."""
    nkw = len(kw_names)
    takes_kw = len(w_iseq.kw_table) > 0 or w_iseq.kwrest >= 0
    # A **splat's Hash is the last argument. It becomes the keywords, stays a positional where the callee declares none, and vanishes when it is empty (vm_args.c:673); `**{}` compiles to a putnil that means the same thing.
    splat_hash = 0
    if kw_splat:
        splat_hash = args[len(args) - 1]
        empty = (splat_hash == value.Q_NIL
                 or rubycall.hash_size(splat_hash) == 0)
        if takes_kw or empty:
            end = len(args) - 1
            assert end >= 0
            args = args[:end]
        if not takes_kw or empty:
            splat_hash = 0
    # Nowhere to place them: CRuby folds them into one trailing positional Hash instead (vm_args.c args_kw_argv_to_hash).
    fold = nkw > 0 and not takes_kw
    lead = w_iseq.nparams
    opt_num = len(w_iseq.opt_table) - 1
    if opt_num < 0:
        opt_num = 0
    post_num = w_iseq.post_num
    rest = w_iseq.rest_start
    post_start = w_iseq.post_start
    # The loader checked these against nlocals; restated so the codewriter sees every virtualizable index as non-negative.
    assert lead >= 0
    assert post_num >= 0
    # vm_args.c:594; a rest parameter makes the maximum unlimited.
    min_argc = lead + post_num
    max_argc = -1 if rest >= 0 else min_argc + opt_num
    n = len(args) - nkw
    if fold:
        n += 1
    if n < min_argc:
        if not is_block:
            _arity_error(n, min_argc, max_argc)
    elif max_argc >= 0 and n > max_argc:
        if not is_block:
            _arity_error(n, min_argc, max_argc)
        # arg_setup_block truncates instead of raising (vm_args.c:884).
        n = max_argc

    # After the arity check, so nothing raises between the hold and the release; an RPython list is no GC root, and the Hash is fresh.
    kw_hash = 0
    if fold:
        args = _kw_to_positional(args, kw_names)
        kw_hash = args[len(args) - 1]
        gcroots.hold(kw_hash)
        kw_names = NO_KEYWORDS
        nkw = 0

    i = 0
    while i < lead:
        if i < n:
            callee.local_set(i, args[i])
        else:
            callee.local_set(i, value.Q_NIL)
        i += 1

    given = n - min_argc
    if given < 0:
        given = 0
    filled = given if given < opt_num else opt_num
    i = 0
    while i < filled:
        callee.local_set(lead + i, args[lead + i])
        i += 1

    if rest >= 0:
        count = given - filled
        values = [0] * count
        i = 0
        while i < count:
            values[i] = args[lead + filled + i]
            i += 1
        # The caller's frame still holds these while the shim copies them onto the machine stack.
        ary = rubycall.ary_new(values)
        assert rest >= 0
        callee.local_set(rest, ary)

    if post_num > 0:
        assert post_start >= 0
        i = 0
        while i < post_num:
            take = n - post_num + i
            if take >= 0 and take < n:
                callee.local_set(post_start + i, args[take])
            else:
                callee.local_set(post_start + i, value.Q_NIL)
            i += 1

    if kw_hash != 0:
        gcroots.release(kw_hash)

    if takes_kw:
        _setup_keywords(w_iseq, callee, args, len(args) - nkw, kw_names,
                        splat_hash)

    if opt_num > 0:
        return w_iseq.opt_table[filled]
    return 0


@unroll_safe
def _kw_to_positional(args, kw_names):
    """A callee with no keyword parameters takes them as one trailing Hash."""
    n = len(args) - len(kw_names)
    out = [0] * (n + 1)
    i = 0
    while i < n:
        out[i] = args[i]
        i += 1
    i = 0
    while i < len(kw_names):
        rubycall.sym_value(kw_names[i])
        i += 1
    h = rubycall.hash_new(len(kw_names))
    i = 0
    while i < len(kw_names):
        rubycall.hash_aset(h, rubycall.sym_value(kw_names[i]), args[n + i])
        i += 1
    out[n] = h
    return out


@unroll_safe
def _setup_keywords(w_iseq, callee, args, base, kw_names, splat_hash=0):
    """vm_args.c args_setup_kw_parameters: match by name, default the rest, and mark every unfilled optional in the kwbits local."""
    table = w_iseq.kw_table
    required = w_iseq.kw_required
    start = w_iseq.kw_start
    nkw = len(kw_names)
    taken = [False] * nkw
    missing = []
    # A **splat is read a declared name at a time; this counts the keys so used up, so the leftovers can be told apart without walking the Hash.
    used = 0
    bits = 0
    i = 0
    while i < len(table):
        found = -1
        j = 0
        while j < nkw:
            if not taken[j] and kw_names[j] == table[i]:
                found = j
                break
            j += 1
        given = value.Q_UNDEF
        if found >= 0:
            taken[found] = True
            given = args[base + found]
        elif splat_hash != 0:
            given = rubycall.hash_lookup(splat_hash,
                                         rubycall.sym_value(table[i]))
            if given != value.Q_UNDEF:
                used += 1
        slot = start + i
        assert slot >= 0
        if given != value.Q_UNDEF:
            callee.local_set(slot, given)
        elif i < required:
            missing.append(table[i])
        elif w_iseq.kw_defaults[i] != value.Q_UNDEF:
            callee.local_set(slot, w_iseq.kw_defaults[i])
        else:
            callee.local_set(slot, value.Q_NIL)
            bits |= 1 << (i - required)
        i += 1
    if len(missing) > 0:
        _keyword_error('missing', missing)

    if w_iseq.kwrest >= 0:
        j = 0
        while j < nkw:
            rubycall.sym_value(kw_names[j])
            j += 1
        if splat_hash != 0:
            rest = _splat_leftovers(w_iseq, splat_hash, used)
        else:
            rest = rubycall.hash_new(nkw)
        j = 0
        while j < nkw:
            if not taken[j]:
                rubycall.hash_aset(rest, rubycall.sym_value(kw_names[j]),
                                   args[base + j])
            j += 1
        slot = w_iseq.kwrest
        assert slot >= 0
        callee.local_set(slot, rest)
    else:
        unknown = []
        j = 0
        while j < nkw:
            if not taken[j]:
                unknown.append(kw_names[j])
            j += 1
        if len(unknown) > 0:
            _keyword_error('unknown', unknown)
        if splat_hash != 0 and used != rubycall.hash_size(splat_hash):
            _splat_unknown(w_iseq, splat_hash, used)

    if w_iseq.kw_bits >= 0:
        slot = w_iseq.kw_bits
        assert slot >= 0
        callee.local_set(slot, value.int2fix(bits))


@dont_look_inside
def _splat_leftovers(w_iseq, splat_hash, used):
    """The **splat's keys that no declared keyword parameter took."""
    rest = rubycall.hash_resurrect(splat_hash)
    if used > 0:
        for mid in w_iseq.kw_table:
            rubycall.hash_delete(rest, rubycall.sym_value(mid))
    return rest


@dont_look_inside
def _splat_unknown(w_iseq, splat_hash, used):
    keys = rubycall.hash_keys(_splat_leftovers(w_iseq, splat_hash, used))
    raise RubyException(rubycall.keyword_error('unknown', keys),
                        'ArgumentError')


@dont_look_inside
def _keyword_error(kind, names):
    keys = []
    for mid in names:
        keys.append(rubycall.sym_value(mid))
    raise RubyException(
        rubycall.keyword_error(kind, rubycall.ary_new(keys)), 'ArgumentError')


@dont_look_inside
def _arity_error(given, min_argc, max_argc):
    raise RubyException(boot.arity_error(given, min_argc, max_argc),
                        'ArgumentError')


@unroll_safe
def _opt_send(frame, mid, argc):
    """The send an opt_* falls through to on Qundef, as vm_insnhelper.c's CALL_SIMPLE_METHOD does; the operands stay on the marked stack."""
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
    if entry is None and argc <= 1:
        # The same native answers invoke gives a named send; a subclass's inherited [] or length lands here via the opt_* fallback.
        if argc == 1:
            v = _native_binop(recv, frame.stack[recv_at + 1], mid)
        else:
            v = helpers.zero_arg(recv, mid)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 \
            and (mid == helpers.LT or mid == helpers.GT
                 or mid == helpers.LE or mid == helpers.GE) \
            and send_owners.comparable != 0 \
            and dispatch.owner_of(klass, mid) == send_owners.comparable:
        # opt_lt and friends fall through here for a Comparable receiver.
        return _comparable_op(frame, mid, recv_at)
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    return rubycall.call(recv, mid, args)


@unroll_safe
def _super_to_cruby(frame, klass, owner, mid, recv_at, argc, kw_splat,
                    kw_names=NO_KEYWORDS):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    return _super_to_cruby_args(frame, klass, owner, mid, recv_at, args,
                                kw_splat, kw_names)


@unroll_safe
def _super_to_cruby_args(frame, klass, owner, mid, recv_at, args, kw_splat,
                         kw_names=NO_KEYWORDS):
    """`super` landing on a method CRuby owns: the method after owner's along klass's chain, bound to the receiver. Literal keywords become the one trailing Hash bind_call passes on as keywords."""
    recv = frame.stack[recv_at]
    if mid == INITIALIZE and len(args) == 0 \
            and owner == value.core_class(value.C_BASIC_OBJECT) \
            and helpers.basic_initialize_pristine():
        _drop(frame, recv_at)
        return value.Q_NIL
    if len(kw_names) > 0:
        args = _kw_to_positional(args, kw_names)
    _drop(frame, recv_at)
    ret = rubycall.call_super(klass, owner, recv, mid, args,
                              kw_splat or len(kw_names) > 0)
    if ret == value.Q_UNDEF:
        raise UnsupportedOperation(
            "super from '%s' reaches a method its owner does not define"
            % symbols.name_of(mid))
    _check_block_error()
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
    if not w_ci.simple and len(w_ci.kw_names) == 0 and not w_ci.kw_splat \
            and not w_ci.splat:
        raise UnsupportedOperation(
            "super in '%s' passes arguments RPyYARV does not support"
            % symbols.name_of(entry.mid))
    if w_ci.kw_splat:
        _kw_splat_hash(frame, recv_at + argc)

    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    klass = promote(value.class_of(recv))
    # CRuby is asked where super lands, since the chain above owner may hold iclasses registry.supers does not.
    owner = dispatch.super_owner(klass, entry.owner, entry.mid)
    target = None
    if owner != value.Q_NIL:
        target = dispatch.lookup_owned(owner, entry.mid)
    if target is None and owner == value.Q_NIL:
        # No super method at all; rb_call_super's NoMethodError needs a CRuby frame, which RPyYARV never has.
        raise UnsupportedOperation(
            "super from '%s' has no superclass method"
            % symbols.name_of(entry.mid))
    if w_ci.splat:
        trailing = 1 if w_ci.kw_splat else len(w_ci.kw_names)
        args = _splat_args(frame, recv_at + 1, argc - trailing, trailing)
        if target is None:
            return _super_to_cruby_args(frame, klass, entry.owner, entry.mid,
                                        recv_at, args, w_ci.kw_splat,
                                        w_ci.kw_names)
        if target.kind != dispatch.KIND_ISEQ:
            return _attr_send_args(frame, target, recv, recv_at, args)
        return _enter_args(frame, target, recv, recv_at, args, entry.mid,
                           None, w_ci.kw_names, w_ci.kw_splat)
    if target is None:
        return _super_to_cruby(frame, klass, entry.owner, entry.mid, recv_at,
                               argc, w_ci.kw_splat, w_ci.kw_names)
    if target.kind != dispatch.KIND_ISEQ:
        return _attr_send(frame, target, recv, recv_at, argc)
    return _enter(frame, target, recv, recv_at, argc,
                  entry.mid, None, w_ci.kw_names, w_ci.kw_splat)


# `alias` and `undef` compile to a send of one of these (vm.c); unseen, the registry shadows what they change in CRuby.
CORE_ALIAS = symbols.intern('core#set_method_alias')
CORE_UNDEF = symbols.intern('core#undef_method')
CORE_GVAR_ALIAS = symbols.intern('core#set_variable_alias')
# Literal keywords beside a **, and a bare `super` forwarding keywords (vm.c:4261).
HASH_MERGE_PTR = symbols.intern('core#hash_merge_ptr')
HASH_MERGE_KWD = symbols.intern('core#hash_merge_kwd')


MODULE_FUNCTION = symbols.intern('module_function')
PRIVATE_CLASS_METHOD = symbols.intern('private_class_method')
ALIAS_METHOD = symbols.intern('alias_method')
INSTANCE_EVAL = symbols.intern('instance_eval')
INSTANCE_EXEC = symbols.intern('instance_exec')
CLASS_EVAL = symbols.intern('class_eval')
MODULE_EVAL = symbols.intern('module_eval')
CORE_LAMBDA = symbols.intern('lambda')
KERNEL_PROC = symbols.intern('proc')


@dont_look_inside
def _singleton_of(recv):
    """The singleton class instance_eval pushes as its cref, or 0 for a receiver that cannot have one, whose `def` then lands where the block was written."""
    if value.is_immediate(recv):
        return 0
    return boot.singleton_class(recv)


@unroll_safe
def _instance_eval(frame, mid, recv, recv_at, argc, w_block):
    """instance_eval/instance_exec with a block: run it here with self rebound, since out through CRuby the block keeps the self it was written with."""
    args = []
    if mid == INSTANCE_EXEC:
        i = 0
        while i < argc:
            args.append(frame.stack[recv_at + 1 + i])
            i += 1
    else:
        args.append(recv)
    sing = _singleton_of(recv)
    cref = None
    if sing != 0:
        cref = _push_cref(_cref_of(frame), sing, True)
    _drop(frame, recv_at)
    return call_block(w_block, args, NO_KEYWORDS, False, recv, cref)


@unroll_safe
def _module_eval_block(frame, recv, recv_at, w_block):
    """class_eval/module_eval with a block, run here as _instance_eval is: through CRuby the block would keep its written cref and a def inside would land privately on Object."""
    args = [recv]
    cref = _push_cref(_cref_of(frame), recv, True)
    _drop(frame, recv_at)
    return call_block(w_block, args, NO_KEYWORDS, False, recv, cref)


def _in_body_of(frame, recv):
    node = frame.cref
    return node is not None and node.klass == recv


@unroll_safe
def _module_function(frame, recv, recv_at, argc):
    """rb_mod_modfunc: with no arguments it flips the body's scope, and every def after it lands both privately here and on the singleton class."""
    if argc == 0:
        frame.module_func = True
        _drop(frame, recv_at)
        return recv
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    # CRuby first, so a name it rejects raises before the registry is touched.
    ret = rubycall.call(recv, MODULE_FUNCTION, args)
    _copy_to_singleton(recv, args)
    return ret


@unroll_safe
def _private_class_method(frame, recv, recv_at, argc):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    # CRuby first, so a name it rejects raises before the registry is touched.
    ret = rubycall.call(recv, PRIVATE_CLASS_METHOD, args)
    _hide_on_singleton(recv, args)
    return ret


@dont_look_inside
def _hide_on_singleton(recv, args):
    klass = boot.singleton_class(recv)
    if klass == 0 or value.is_immediate(klass):
        return
    for v in args:
        mid = symbols.intern(_attr_name(v))
        entry = dispatch.own_lookup(klass, mid)
        if entry is None or entry.kind != dispatch.KIND_ISEQ:
            continue
        dispatch.define(klass, mid, entry.w_iseq, True, entry.cref,
                        entry.lexical)


@dont_look_inside
def _copy_to_singleton(klass, args):
    for v in args:
        mid = symbols.intern(_attr_name(v))
        entry = dispatch.own_lookup(klass, mid)
        if entry is None or entry.kind != dispatch.KIND_ISEQ:
            continue
        dispatch.define(klass, mid, entry.w_iseq, True, entry.cref,
                        entry.lexical)
        dispatch.define_singleton(klass, mid, entry.w_iseq, entry.cref,
                                  entry.lexical)


def _core_method(frame, mid, recv, recv_at, argc):
    if argc != 3 and mid == CORE_ALIAS:
        raise UnsupportedOperation('core#set_method_alias needs 3 arguments')
    if argc != 2 and mid == CORE_UNDEF:
        raise UnsupportedOperation('core#undef_method needs 2 arguments')
    cbase = frame.stack[recv_at + 1]
    if value.is_immediate(cbase) or not boot.is_class(cbase):
        raise UnsupportedOperation('alias or undef outside a class body')
    name = _sym_mid(frame.stack[recv_at + 2])
    if mid == CORE_UNDEF:
        dispatch.undefine(cbase, name)
        args = [cbase, frame.stack[recv_at + 2]]
        _drop(frame, recv_at)
        ret = rubycall.call(recv, mid, args)
        helpers.refresh()
        return ret
    old = _sym_mid(frame.stack[recv_at + 3])
    entry = dispatch.own_lookup(cbase, old)
    dispatch.undefine(cbase, name)
    if entry is not None and entry.kind == dispatch.KIND_ISEQ:
        # An RPyYARV method: the alias is a second name for the same body, and define installs the trampoline CRuby resolves it through.
        dispatch.define(cbase, name, entry.w_iseq, entry.private,
                        entry.cref, entry.lexical)
        _drop(frame, recv_at)
        return value.Q_NIL
    if entry is not None:
        # An attr entry: register the fast path here, then let CRuby alias its own attr method too. define_attr installs no trampoline, so without this the new name would exist only in RPyYARV's registry -- invisible to respond_to?, instance_methods and a later alias of it.
        dispatch.define_attr(cbase, name, entry.ivar, entry.kind)
    args = [cbase, frame.stack[recv_at + 2], frame.stack[recv_at + 3]]
    _drop(frame, recv_at)
    ret = rubycall.call(recv, mid, args)
    helpers.refresh()
    return ret


def _alias_method(frame, recv, recv_at):
    """Module#alias_method, as _core_method runs the alias keyword: an ISEQ alias never reaches CRuby, whose copy would be the old name's trampoline and so track a later redefinition of the old name (liquid-c saves ruby_parse this way before replacing parse)."""
    new_v = frame.stack[recv_at + 1]
    old_v = frame.stack[recv_at + 2]
    if boot.is_symbol(new_v) and boot.is_symbol(old_v):
        name = symbols.intern(boot.sym_of(new_v))
        old = symbols.intern(boot.sym_of(old_v))
        entry = dispatch.lookup(recv, old)
        if entry is not None:
            dispatch.undefine(recv, name)
            if entry.kind == dispatch.KIND_ISEQ:
                dispatch.define(recv, name, entry.w_iseq, entry.private,
                                entry.cref, entry.lexical)
                _drop(frame, recv_at)
                return new_v
            dispatch.define_attr(recv, name, entry.ivar, entry.kind)
    args = [frame.stack[recv_at + 1], frame.stack[recv_at + 2]]
    _drop(frame, recv_at)
    ret = rubycall.call(recv, ALIAS_METHOD, args)
    helpers.refresh()
    return ret


@dont_look_inside
def _sym_mid(v):
    if not boot.is_symbol(v):
        raise UnsupportedOperation('alias or undef names something '
                                   'that is not a Symbol')
    return symbols.intern(boot.sym_of(v))


class _Blocks(object):
    """Blocks C refers to by integer handle only, since RPython's GC moves objects; a Proc's handle is never given back, as the Proc outlives every frame."""
    def __init__(self):
        self.table = []         # handle -> W_Block, None for a free slot
        # handle -> the self the block was handed over under, so a yield can tell an instance_eval substitution from the ordinary case.
        self.selves = []
        self.free = []          # handles whose GC owner died
        self.by_proc = {}       # a materialised Proc -> the block behind it
        self.error = None       # an RPython error the callback could not raise
        self.exc = None         # likewise, a Ruby exception
        self.jump = None        # likewise, a break or a non-local return


blocks = _Blocks()


def _alloc_handle(w_block):
    # Slots come back only when their GC owner died, so a stored block (Hash default_proc, a saved callback) stays callable.
    while True:
        h = boot.pop_dead_handle()
        if h < 0:
            break
        _release_handle(h)
    here = boot.current_receiver()
    if len(blocks.free) > 0:
        h = blocks.free.pop()
        blocks.table[h] = w_block
        blocks.selves[h] = here
        return h
    blocks.table.append(w_block)
    blocks.selves.append(here)
    return len(blocks.table) - 1


def _release_handle(h):
    w_block = blocks.table[h]
    if w_block is not None:
        v = w_block.proc_value
        # The Proc died; a later escape must build a fresh one.
        w_block.proc_value = 0
        if v in blocks.by_proc and blocks.by_proc[v] is w_block:
            del blocks.by_proc[v]
    blocks.table[h] = None
    blocks.selves[h] = 0
    blocks.free.append(h)


class _Proxy(object):
    # Quasi-immutable, so the compare below folds away; a prebuilt instance cannot use a plain immutable field (value._Classes).
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


# rb_block_param_proxy's stand-in, pushed instead of a Proc (insns.def:144): a Symbol, so unmarked, and it never leaves those sites.
proxy = _Proxy()


class _Fiber(object):
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


fiber = _Fiber()


class _Encodings(object):
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


encodings = _Encodings()

ENC_FIND = symbols.intern('find')
# Encoding.find is a pure lookup and Encodings are immortal, so one protected call per distinct name is enough.
enc_cache = {}

SPACESHIP_CI = W_CallInfo(helpers.SPACESHIP, 1)


@unroll_safe
def _comparable_op(frame, mid, recv_at):
    """Comparable#< and friends: run <=> natively instead of bouncing out to compar.c and back in through the trampoline."""
    recv = frame.stack[recv_at]
    arg = frame.stack[recv_at + 1]
    cmp = invoke(frame, SPACESHIP_CI)
    if value.is_fixnum(cmp):
        c = value.fix2int(cmp)
        if mid == helpers.LT:
            return value.newbool(c < 0)
        if mid == helpers.LE:
            return value.newbool(c <= 0)
        if mid == helpers.GT:
            return value.newbool(c > 0)
        return value.newbool(c >= 0)
    # nil or an exotic Integer: CRuby's own operator raises the ArgumentError.
    gcroots.hold(recv)
    gcroots.hold(arg)
    try:
        return rubycall.call(recv, mid, [arg])
    finally:
        gcroots.release(arg)
        gcroots.release(recv)


def _encoding_find(frame, recv, recv_at):
    name_v = frame.stack[recv_at + 1]
    if value.is_immediate(name_v) or not boot.is_string(name_v):
        return value.Q_UNDEF
    name = boot.str_of(name_v)
    if name in enc_cache:
        _drop(frame, recv_at)
        debug.count_native()
        return enc_cache[name]
    _drop(frame, recv_at)
    v = rubycall.call(recv, ENC_FIND, [name_v])
    enc_cache[name] = v
    return v

PROXY_NAME = '__rpyyarv_block_param_proxy__'


def _sub_self(handle, cruby_self):
    """Q_UNDEF leaves the block's own self alone; another value is the self CRuby yielded under, which only instance_eval substitutes."""
    v = boot.as_signed(cruby_self)
    if v == blocks.selves[handle]:
        return value.Q_UNDEF
    return v


def block_callback(handle, argc, argv, cruby_self):
    """Called from C; no RPython exception may escape into libruby, so a failure is re-raised once the call has returned. cruby_self is Qundef unless the yielding frame substituted one, as instance_eval does."""
    if blocks.error is not None or blocks.exc is not None \
            or blocks.jump is not None:
        return boot.as_value(value.Q_NIL)
    w_block = blocks.table[handle]
    if w_block is None:
        blocks.error = UnsupportedOperation(
            'a block was called after its handle was released')
        return boot.as_value(value.Q_NIL)
    args = boot.read_values(argv, argc)
    foreign = _enter_foreign_stack()
    try:
        # A cref of its own only comes from an instance_eval RPyYARV ran; here CRuby owns the frame, so the block keeps the one it was written with.
        return boot.as_value(call_block(w_block, args, NO_KEYWORDS, False,
                                        _sub_self(handle, cruby_self)))
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
        # Parked like the rest: returning normally would let CRuby call the block again on an exhausted stack.
        check_stack_overflow()
        blocks.error = UnsupportedOperation(STACK_TOO_DEEP)
        return _park_unwind()
    finally:
        if foreign:
            _leave_foreign_stack()


STACK_TOO_DEEP = 'the call is nested too deeply for RPyYARV\'s stack'


@dont_look_inside
def _park_unwind():
    """An RPython exception cannot cross libruby's frames, so the shim raises on its behalf and rb_protect hands control back."""
    boot.set_block_unwind()
    return boot.as_value(value.Q_NIL)


TRAMP_OK = 0
TRAMP_RAISE = 1
TRAMP_UNSUPPORTED = 2
TRAMP_UNWIND = 3


def trampoline_callback(self_v, rid, argc, argv, blockv, kw, statusp, errp):
    """Called from C when CRuby dispatched to an RPyYARV method; no RPython exception may reach libruby, so failures leave via statusp/errp."""
    boot.store_int(statusp, TRAMP_OK)
    boot.store_value(errp, value.Q_NIL)
    recv = boot.as_signed(self_v)
    mid = rubycall.mid_of_rid(boot.as_signed(rid))
    # argv lives on CRuby's VM stack for the whole call, so the copy needs no root until it lands in the callee's frame.
    args = boot.read_values(argv, argc)
    w_block = None
    proc_v = boot.as_signed(blockv)
    if proc_v != value.Q_NIL:
        w_block = block_mod.from_proc(proc_v)
    foreign = _enter_foreign_stack()
    try:
        return boot.as_value(_from_cruby(recv, mid, args, w_block,
                                         boot.as_int(kw) != 0))
    except RubyException, e:
        boot.store_int(statusp, TRAMP_RAISE)
        boot.store_value(errp, e.value)
    except block_mod.BlockJump, e:
        # Aimed past this call: the shim raises so libruby unwinds its frames, and the caller's rb_protect hands control back.
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
    finally:
        if foreign:
            _leave_foreign_stack()
    return boot.as_value(value.Q_NIL)


class _Foreign(object):
    def __init__(self):
        self.depth = 0


foreign_stack = _Foreign()


@dont_look_inside
def _enter_foreign_stack():
    """CRuby re-entered RPyYARV on a machine stack RPython did not measure, a Fiber's; the depth check reads every address on it as an overflow, so it is off for the duration."""
    # ponytail: off, not re-based -- a run-away recursion started on a Fiber's stack segfaults instead of raising. Re-basing wants an rstack primitive that does not exist.
    if not on_foreign_stack():
        return False
    foreign_stack.depth += 1
    unchecked_stack_start()
    return True


@dont_look_inside
def _leave_foreign_stack():
    foreign_stack.depth -= 1
    if foreign_stack.depth == 0:
        unchecked_stack_stop()


@dont_look_inside
def _tramp_failed(statusp, errp, msg):
    boot.store_int(statusp, TRAMP_UNSUPPORTED)
    boot.store_value(errp, boot.str_new('[rpyyarv] %s' % msg))


def _from_cruby(recv, mid, args, w_block, kw_splat=False):
    """The send half of the trampoline: the registry's own lookup, with the arguments CRuby already parsed; kw_splat says its last one is a keyword Hash."""
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
    callee = Frame(callee_iseq, recv, None, entry)
    callee.block = w_block
    pc = 0
    argc = len(args)
    if callee_iseq.simple_params and not kw_splat:
        if argc != callee_iseq.nparams:
            _arity_error(argc, callee_iseq.nparams, callee_iseq.nparams)
        i = 0
        while i < argc:
            callee.local_set(i, args[i])
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        pc = setup_params(callee_iseq, callee, args, False, NO_KEYWORDS,
                          kw_splat)
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
def _call_with_block(recv, mid, args, w_block, kw=False):
    if recv == fiber.value and mid == NEW and not kw:
        raise UnsupportedOperation(
            'Fiber.new with an RPyYARV block is not supported')
    handle = _alloc_handle(w_block)
    # No release here: the handle's owner object dies with the ifunc, and _alloc_handle reclaims the slot then.
    try:
        ret = rubycall.call_with_block(recv, mid, args, handle, kw)
    except RubyException:
        # The CRuby method failed; whatever the block parked before that is the reason, and takes precedence.
        _check_block_error()
        raise
    _check_block_error()
    return ret


def _check_block_error():
    """Raises what a callback could not raise through libruby's frames, now that RPyYARV::Unwind brought control back."""
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
    """A real Proc for an escaping block, as rb_vm_bh_to_procval builds one (vm_insnhelper.c:543); memoised for one Proc identity until the Proc's own death releases the handle."""
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
SLICE = symbols.intern('slice')


def _is_proxy_call(mid):
    """The proxy runs the block itself for these; anything else builds the Proc first, as Proc#arity and friends need a real one."""
    return mid == CALL or mid == YIELD or mid == AREF or mid == EQQ_


ARITY = symbols.intern('arity')
LAMBDA_P = symbols.intern('lambda?')


def _iseq_arity(w_iseq):
    """rb_proc_arity over iseq_min_max_arity (proc.c:1120): min when fixed, -(min+1) otherwise."""
    opt_num = len(w_iseq.opt_table) - 1
    if opt_num < 0:
        opt_num = 0
    has_kw = len(w_iseq.kw_table) > 0 or w_iseq.kwrest >= 0
    min_argc = w_iseq.nparams + w_iseq.post_num \
        + (1 if w_iseq.kw_required > 0 else 0)
    if w_iseq.rest_start >= 0:
        return -min_argc - 1
    max_argc = w_iseq.nparams + opt_num + w_iseq.post_num \
        + (1 if has_kw else 0)
    return min_argc if min_argc == max_argc else -min_argc - 1


@dont_look_inside
def _block_from_value(frame_block, v):
    """The block a `&arg` call site passes on, as vm_caller_setup_arg_block reads it (vm_args.c:1116); takes the frame's block, not the frame, so it never escapes the virtualizable."""
    if v == value.Q_NIL:
        return None
    if v == proxy.value:
        # The frame's own block, without ever having built a Proc for it.
        return frame_block
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
def _block_send(frame, mid, recv_at, argc, w_block,
                kw_names=NO_KEYWORDS, kw_splat=False):
    """A send whose receiver stands for a block RPyYARV holds: the block-param proxy (compile.c:9564), or a Proc it materialised."""
    args = [0] * argc
    i = 0
    while i < argc:
        args[i] = frame.stack[recv_at + 1 + i]
        i += 1
    _drop(frame, recv_at)
    return _block_send_args(mid, w_block, args, kw_names, kw_splat)


@unroll_safe
def _block_send_args(mid, w_block, args, kw_names=NO_KEYWORDS,
                     kw_splat=False):
    if _is_proxy_call(mid):
        if w_block is None:
            raise UnsupportedOperation('the block parameter is nil')
        return call_block(w_block, args, kw_names, kw_splat)
    if w_block is not None and w_block.kind == block_mod.KIND_ISEQ \
            and len(args) == 0 and len(kw_names) == 0 and not kw_splat:
        # The materialised Proc wraps a C yielder, so these must come from the ISeq it stands for.
        if mid == ARITY:
            return value.int2fix(_iseq_arity(w_block.w_iseq))
        if mid == LAMBDA_P:
            return value.newbool(w_block.is_lambda)
    if len(kw_names) > 0:
        args = _kw_to_positional(args, kw_names)
    if len(kw_names) > 0 or kw_splat:
        return rubycall.call_kw(_to_proc(w_block), mid, args)
    return rubycall.call(_to_proc(w_block), mid, args)


@unroll_safe
def call_block(w_block, args, kw_names=NO_KEYWORDS, kw_splat=False,
               self_val=value.Q_UNDEF, cref=None):
    """Run a block's ISeq in a frame whose locals chain to the defining one; instance_eval passes the self and cref it rebinds them to."""
    keyed = len(kw_names) > 0 or kw_splat
    if w_block.kind != block_mod.KIND_ISEQ:
        if keyed:
            return _call_foreign_block_kw(w_block, args, kw_names, kw_splat)
        return _call_foreign_block(w_block, args)
    # Promoted here, not left to the merge point below: the frame's arrays then take constant sizes instead of an out-of-line malloc.
    b_iseq = promote(w_block.w_iseq)
    outer = w_block.frame
    if self_val == value.Q_UNDEF:
        self_val = outer.self_val
    if cref is None:
        cref = outer.cref
    callee = Frame(b_iseq, self_val, cref, outer.entry)
    callee.defining_frame = outer
    callee.block = w_block.outer
    callee.own_block = w_block
    if w_block.is_lambda:
        return _run_lambda(w_block, b_iseq, callee, args, kw_names, kw_splat)
    if b_iseq.autosplat and len(args) == 1 and not keyed:
        args = _autosplat(args)
    pc = 0
    if b_iseq.simple_params and not keyed:
        n = len(args)
        if n > b_iseq.nparams:
            n = b_iseq.nparams
        i = 0
        while i < n:
            callee.local_set(i, args[i])
            i += 1
    else:
        pc = setup_params(b_iseq, callee, args, True, kw_names, kw_splat)
    try:
        return execute(b_iseq, callee, pc)
    except block_mod.BlockNext, e:
        return e.value


@unroll_safe
def _run_lambda(w_block, b_iseq, callee, args, kw_names, kw_splat):
    """arg_setup_method, not arg_setup_block: exact arity, no autosplat; return and break leave the lambda itself (vm_insnhelper.c:1832)."""
    pc = setup_params(b_iseq, callee, args, False, kw_names, kw_splat)
    try:
        return execute(b_iseq, callee, pc)
    except block_mod.BlockNext, e:
        return e.value
    except block_mod.BlockReturn, e:
        if e.frame is not callee:
            raise
        return e.value
    except block_mod.BlockBreak, e:
        if e.w_block is not w_block:
            raise
        return e.value
    finally:
        # A later return aimed here from an escaped inner proc is the orphaned LocalJumpError.
        callee.dead = True


@dont_look_inside
def _call_foreign_block_kw(w_block, args, kw_names, kw_splat):
    """The same, handed the keywords as the one trailing Hash RB_PASS_KEYWORDS names."""
    if w_block.kind != block_mod.KIND_PROC:
        raise UnsupportedOperation('a &:symbol block takes no keywords')
    if not kw_splat:
        args = _kw_to_positional(args, kw_names)
    elif len(args) > 0 and args[len(args) - 1] == value.Q_NIL:
        end = len(args) - 1
        assert end >= 0
        return rubycall.call(w_block.proc_value, CALL, args[:end])
    return rubycall.call_kw(w_block.proc_value, CALL, args)


@dont_look_inside
def _call_foreign_block(w_block, args):
    """A block that is not RPyYARV's own: a Proc from CRuby, or `&:sym` (rb_sym_to_proc, vm_insnhelper.c:552)."""
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
    """One yielded value spread over block parameters. TODO: CRuby asks for to_ary (vm_args.c:863), this only takes a real Array."""
    v = args[0]
    if value.is_immediate(v):
        return args
    if value.is_plain_array(v):
        # Read in place: this runs once per yielded element, and a call per element showed up in the profile.
        n = value.ary_len(v)
        out = [0] * n
        i = 0
        while i < n:
            out[i] = value.ary_at(v, i)
            i += 1
        return out
    if not boot.is_array(v):
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
    """The frame `level` steps up the block chain; its locals live on the heap (shares_locals), so reading them never forces its virtualizable."""
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
    if w_ci.kw_splat:
        _kw_splat_hash(frame, at + argc - 1)
    if w_ci.splat:
        trailing = 1 if w_ci.kw_splat else len(w_ci.kw_names)
        args = _splat_args(frame, at, argc - trailing, trailing)
    else:
        args = [0] * argc
        i = 0
        while i < argc:
            args[i] = frame.stack[at + i]
            i += 1
    _drop(frame, at)
    return call_block(w_block, args, w_ci.kw_names, w_ci.kw_splat)


class Throw(object):
    """A throw in flight, as vm_exec_handle_exception takes it; not an exception itself, _rethrow turns it back into one."""
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
    if throw.kind == PENDING_RETRY:
        raise block_mod.BlockRetry()
    raise block_mod.BlockNext(throw.value)


# A longer defining-frame chain is corrupt; the walk has to terminate for the tracer.
MAX_SCOPES = 256


def _return_target(frame):
    """The frame a non-local return leaves: the nearest lambda frame, else the outermost of the block's chain, CRuby's local EP (vm_insnhelper.c:1834)."""
    f = frame
    n = 0
    while n < MAX_SCOPES:
        if f.own_block is not None and f.own_block.is_lambda:
            return f
        if f.defining_frame is None:
            return f
        f = f.defining_frame
        n += 1
    return f


@dont_look_inside
def _local_jump_error(mesg, v, reason):
    return RubyException(boot.local_jump_error(mesg, v, reason), 'return')


def _return(frame, v):
    """`return` from a block; a dead target or one that is not a method is the orphaned-Proc LocalJumpError (vm_insnhelper.c:1926)."""
    target = _return_target(frame)
    is_lambda = target.own_block is not None and target.own_block.is_lambda
    if target.dead or not (target.w_iseq.catches_return or is_lambda):
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
        raise block_mod.BlockRetry()
    raise UnsupportedOperation(
        'throw with tag %d (redo) is not supported' % tag)


def _catch_for(iseq, epc, kind):
    """The first catch-table entry covering epc, in CRuby's search order (vm.c:2911); a break or a next takes only an ensure."""
    catches = iseq.catches
    i = 0
    while i < len(catches):
        entry = catches[i]
        if entry.start < epc and epc <= entry.end:
            if entry.kind == CATCH_ENSURE or \
                    (entry.kind == CATCH_RESCUE and kind == PENDING_RAISE) or \
                    (entry.kind == CATCH_RETRY and kind == PENDING_RETRY):
                return entry
        i += 1
    return None


def _run_catch(frame, entry, throw):
    """A catch ISeq runs in its own frame, chained to the raising one's locals the way vm.c:3014 pushes it with the previous EP."""
    w_iseq = entry.w_iseq
    callee = Frame(w_iseq, frame.self_val, frame.cref, frame.entry)
    callee.defining_frame = frame
    callee.block = frame.block
    callee.own_block = frame.own_block
    if w_iseq.nlocals > 0:
        # Local 0 is `$!`; for a break or a next nothing reads it.
        callee.local_set(0, throw.value if throw.kind == PENDING_RAISE
                         else value.Q_NIL)
    callee.pending_kind = throw.kind
    callee.pending_value = throw.value
    callee.pending_block = throw.w_block
    callee.pending_frame = throw.target
    return _run_with_errinfo(w_iseq, callee, callee.local_get(0)
                             if w_iseq.nlocals > 0 else value.Q_NIL)


def _run_with_errinfo(w_iseq, callee, errinfo):
    """`$!` and a bare `raise` read ec->errinfo, since RPyYARV pushes no CRuby rescue frame for rb_ec_get_errinfo to find."""
    prev = rubycall.swap_errinfo(errinfo)
    try:
        return execute(w_iseq, callee)
    finally:
        rubycall.swap_errinfo(prev)


def _unwind(iseq, frame, throw, epc):
    """Run the entries covering epc until one completes and answer the resume pc; re-raises when the frame handles nothing."""
    while True:
        entry = _catch_for(iseq, epc, throw.kind)
        if entry is None:
            _rethrow(throw)
        frame.reset_sp(entry.sp)
        if entry.kind == CATCH_RETRY:
            return entry.cont
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
        except block_mod.BlockRetry:
            throw = Throw(PENDING_RETRY, value.Q_NIL)
        else:
            frame.reset_sp(entry.sp)
            frame.push(result)
            return entry.cont
        # The catch ISeq threw in turn; cont is where the frame's pc stands.
        epc = entry.cont


def configure_jitparams():
    """RPYYARV_JITPARAM tunes the JIT the way pypy's --jit does, so a parameter sweep costs no translation."""
    spec = os.environ.get('RPYYARV_JITPARAM')
    # Ruby methods commonly become hot before a loop backedge does. PyPy's
    # generic default (1619) left even repeatedly-called 30k-method workloads
    # interpreted; 100 captures them without the broad compile-time regressions
    # seen at 30. An explicit environment setting still replaces this default.
    # Eager bridges and roomier retraces: branchy code (rubykon's MCTS) needs its bridges anyway, and compiling them late is the slow mode.
    set_user_param(jitdriver, spec if spec else
                   'function_threshold=100,trace_eagerness=50,'
                   'retrace_limit=25,max_retrace_guards=60')


def install():
    configure_reselection()
    configure_jitparams()
    boot.rb_patch_method_equality()
    boot.install_block_callback(block_callback)
    boot.install_trampoline_callback(trampoline_callback)
    gcroots.register_blocks(blocks)
    # A Symbol, so it is an immediate no mark hook has to reach.
    proxy.value = boot.sym_new(PROXY_NAME)
    fiber.value = dispatch.const_get(value.core_class(value.C_OBJECT),
                                     symbols.intern('Fiber'))
    # Asked before any Ruby code runs, so these are the pristine owners.
    send_owners.kernel = dispatch.owner_of(
        value.core_class(value.C_OBJECT), SEND)
    helpers.modules.kernel = send_owners.kernel
    send_owners.basic = dispatch.owner_of(
        value.core_class(value.C_BASIC_OBJECT), SEND2)
    send_owners.eval = dispatch.owner_of(
        value.core_class(value.C_OBJECT), EVAL)
    send_owners.string_getbyte = dispatch.owner_of(
        value.core_class(value.C_STRING), GETBYTE)
    send_owners.string_setbyte = dispatch.owner_of(
        value.core_class(value.C_STRING), SETBYTE)
    send_owners.array_each_slice = dispatch.owner_of(
        value.core_class(value.C_ARRAY), EACH_SLICE)
    send_owners.comparable = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Comparable'))
    encodings.value = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Encoding'))


@unroll_safe
def _local_frame(frame, packed):
    if packed == (packed & optable.LOCAL_SLOT_MASK):
        return frame
    return _outer_frame(frame, packed >> optable.LOCAL_LEVEL_SHIFT)


@unroll_safe
def _drop(frame, sp):
    while frame.sp > sp:
        frame.pop()


@unroll_safe
def _pushtoarray(frame, n):
    """rb_ary_cat of the n topmost values onto the Array under them, which stays on the stack as the result."""
    at = frame.sp - n
    if at < 1:
        raise UnsupportedOperation('pushtoarray %d underflows the stack' % n)
    # Restated so the codewriter sees every stack index as non-negative.
    below = at - 1
    assert below >= 0
    ary = frame.stack[below]
    base = _ary_len(ary)
    i = 0
    while i < n:
        j = at + i
        assert j >= 0
        rubycall.ary_store(ary, base + i, frame.stack[j])
        i += 1
    _drop(frame, at)


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
    # Copied but not popped: the frame marks them until the shim has them on the machine stack.
    values = [0] * n
    i = 0
    while i < n:
        values[i] = frame.stack[at + i]
        i += 1
    v = rubycall.ary_new(values)
    _drop(frame, at)
    return v


# vm_core.h's enum vm_opt_newarray_send_type, indexed by method-1; the loader refuses the entries optable.NEWARRAY_SEND_ARGC marks unsupported.
NEWARRAY_SEND_MID = [helpers.MAX, helpers.MIN, helpers.HASH, helpers.PACK,
                     helpers.PACK, helpers.INCLUDE_P]


@unroll_safe
def _newarray_send(frame, n, meth):
    """The temp array built and the method sent, as vm_opt_newarray_send falls back to; the trailing argument of include?/pack is not part of it."""
    argc = optable.NEWARRAY_SEND_ARGC[meth - 1]
    if argc == 2:
        buffer = frame.pop()
        arg = frame.pop()
        count = n - 2
        at = frame.sp - count
        if at < 0 or count < 0:
            raise UnsupportedOperation(
                'opt_newarray_send %d underflows the stack' % n)
        values = [0] * count
        i = 0
        while i < count:
            values[i] = frame.stack[at + i]
            i += 1
        v_ary = rubycall.ary_new(values)
        _drop(frame, at)
        kwargs = boot.hash_new(1)
        boot.hash_aset(kwargs, rubycall.sym_value(BUFFER), buffer)
        return rubycall.call_kw(v_ary, helpers.PACK, [arg, kwargs])
    at = frame.sp - n
    m = n - argc
    if at < 0 or m < 0:
        raise UnsupportedOperation('opt_newarray_send %d underflows the stack'
                                   % n)
    values = [0] * m
    i = 0
    while i < m:
        values[i] = frame.stack[at + i]
        i += 1
    arg = 0
    if argc == 1:
        top = frame.sp - 1
        assert top >= 0
        arg = frame.stack[top]
    v_ary = rubycall.ary_new(values)
    _drop(frame, at)
    frame.push(v_ary)
    if argc == 1:
        frame.push(arg)
    return _opt_send(frame, NEWARRAY_SEND_MID[meth - 1], argc)


@unroll_safe
def _newhash(frame, n):
    """n/2 key/value pairs, left in the marked frame until each rb_hash_aset has copied them into the Hash."""
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


@unroll_safe
def _expand(frame, v, n, flag=0):
    """vm_expandarray: flag 1 pushes the rest as an Array, flag 2 fills from the end."""
    if not value.is_array(v):
        v = boot.ary_to_ary(v)
    size = value.ary_len(v)
    if flag & 2:
        i = 0
        while i < n - size:
            frame.push(value.Q_NIL)
            i += 1
        j = 0
        while i < n:
            frame.push(value.ary_at(v, size - j - 1))
            i += 1
            j += 1
        if flag & 1:
            head = size - j
            assert head >= 0
            frame.push(boot.ary_subseq(v, 0, head))
        return
    if flag & 1:
        if n > size:
            frame.push(boot.ary_subseq(v, size, 0))
        else:
            frame.push(boot.ary_subseq(v, n, size - n))
    i = n - 1
    while i >= 0:
        if i < size:
            frame.push(value.ary_at(v, i))
        else:
            frame.push(value.Q_NIL)
        i -= 1


class _VMCore(object):
    # Quasi-immutable, not immutable: a prebuilt instance's plain immutable field would fold to the 0 it holds before boot.
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


vm_core = _VMCore()


@dont_look_inside
def _vm_core():
    """RubyVM::FrozenCore, receiver of the core# methods (vm_insnhelper.c:5668)."""
    if vm_core.value == 0:
        v = boot.vm_core()
        boot.gc_register(v)
        vm_core.value = v
    return vm_core.value


def _const_path(frame, iseq, idx):
    """A per-site memo of _const_walk; the global cache below it stays the fallback."""
    # Keyed on the innermost class, not the chain: _push_cref interns one node per (outer, class), and a site's outer is fixed by where its ISeq sits, so the two agree.
    base = _const_base(frame)
    entry = dispatch.const_site(iseq.path_sites[idx], dispatch.consts.version)
    if entry is not None and entry.base == base:
        return entry.value
    return _const_path_miss(iseq.path_sites[idx], base, _cref_of(frame),
                            iseq.paths[idx])


@dont_look_inside
def _const_path_miss(site, base, cref, path):
    v = _const_walk(cref, path)
    dispatch.const_site_fill(site, base, v)
    return v


def _const_walk(cref, path):
    """vm_get_ev_const_chain; a leading empty segment is `::Foo`."""
    # An id compare, not a name lookup: the dict read would stay in the trace.
    if path[0] == ROOT_CBASE:
        base = value.core_class(value.C_OBJECT)
    else:
        base = _const_lexical(cref, path[0])
    i = 1
    while i < len(path):
        base = dispatch.const_get(base, path[i])
        i += 1
    return base


def _const_lexical(cref, mid):
    """vm_get_ev_const with a nil cbase: each lexical scope's own table innermost outward, then the innermost scope's ancestors and Object."""
    node = cref
    # The outermost entry is the toplevel Object, which only the walk below covers.
    while node.outer is not None:
        if not node.by_eval:
            v = dispatch.const_at(node.klass, mid)
            if v != value.Q_UNDEF:
                return v
        node = node.outer
    return dispatch.const_get(_cref_klass(cref), mid)


def _cref_klass(cref):
    # const_base, not klass: a scope instance_eval pushed names no constants of its own (vm_get_const_base).
    if cref.const_base == 0:
        return value.core_class(value.C_OBJECT)
    return cref.const_base


def _run_once(frame, iseq, idx):
    """The body of a `once` instruction, run in a frame chained to this one as a block's is; the result is cached for every later execution."""
    body = iseq.iseqs[idx]
    callee = Frame(body, frame.self_val, _cref_of(frame), frame.entry)
    callee.defining_frame = frame
    v = execute(body, callee)
    iseq.once_cache[idx] = v
    return v


@dont_look_inside
def _cvar_base(cref):
    """vm_get_cvar_base: the innermost lexical scope that is a real class, so a `class << self` or an instance_eval scope steps aside. Takes the cref, not the frame, so it never escapes the virtualizable."""
    node = cref
    while node is not None:
        if node.klass != 0 and not node.by_eval \
                and not boot.is_singleton_class(node.klass):
            return node.klass
        if node.outer is None:
            break
        node = node.outer
    return value.core_class(value.C_OBJECT)


@dont_look_inside
def _cvar_get(cref, mid):
    return boot.cvar_get(_cvar_base(cref), rubycall.rid(mid))


@dont_look_inside
def _cvar_set(cref, mid, v):
    boot.cvar_set(_cvar_base(cref), rubycall.rid(mid), v)


def _const_base(frame):
    """The cbase a `class Foo::Bar` or a setconstant resolves against."""
    node = frame.cref
    if node is not None and node.const_base != 0:
        return node.const_base
    entry = frame.entry
    if entry is not None and entry.cref != 0:
        return entry.cref
    return value.core_class(value.C_OBJECT)


def _defined_const(cref, rid):
    node = cref
    while node.outer is not None:
        if boot.const_defined(node.klass, rid, 0):
            return True
        node = node.outer
    return boot.const_defined(_cref_klass(cref), rid, 1)


def _defined(frame, kind, obj, recv):
    mid = _name_mid(obj)
    if mid == rubycall.NO_MID:
        return False
    rid = rubycall.rid(mid)
    if kind == DEFINED_IVAR:
        return boot.ivar_defined(frame.self_val, rid)
    if kind == DEFINED_CVAR:
        return boot.cvar_defined(_cvar_base(_cref_of(frame)), rid)
    if kind == DEFINED_CONST:
        return _defined_const(_cref_of(frame), rid)
    if kind == DEFINED_CONST_FROM:
        return recv != value.Q_NIL and boot.const_defined(recv, rid, 1)
    if kind == DEFINED_FUNC:
        return boot.method_defined(recv, rid, 1)
    if kind == DEFINED_METHOD:
        return boot.method_defined(recv, rid, 0)
    if kind == DEFINED_YIELD:
        return frame.block is not None
    raise UnsupportedOperation('defined? type %d is not implemented' % kind)


def _defineclass(frame, mid, w_body, cbase, super_v, is_module=False):
    if is_module:
        klass = dispatch.define_module(cbase, mid)
    else:
        klass = dispatch.define_class(cbase, mid, super_v)
    body = Frame(w_body, klass, _push_cref(_cref_of(frame), klass))
    ret = execute(w_body, body)
    # Reopening a class is where CRuby-side operator redefinitions show up.
    helpers.refresh()
    return ret


def _definesingletonclass(frame, w_body, obj):
    klass = boot.singleton_class(obj)
    body = Frame(w_body, klass, _push_cref(_cref_of(frame), klass))
    ret = execute(w_body, body)
    helpers.refresh()
    return ret


def _opt_new_alloc(klass):
    """A fresh instance, or 0 for the miss branch; only classes RPyYARV made are known to have kept Class#new."""
    # Promoted, so both tests below fold to a constant and only the allocation is left in the trace.
    klass = promote(klass)
    if not dispatch.is_known_class(klass):
        return 0
    if helpers.ary_new_pristine(klass):
        # The miss branch's `send new` is where _array_new runs; alloc plus a separate initialize would leave CRuby to fill it.
        return 0
    # A `def self.new` (liquid-c's ResourceLimits) must win over the alloc.
    if dispatch.owner_of(promote(value.class_of(klass)), NEW) != \
            value.core_class(value.C_CLASS):
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
        # Module#=== is rb_obj_is_kind_of, so this skips a send. TODO: a subclass redefining #=== is ignored, as in vm_opt_*.
        return boot.obj_is_kind_of(target, pattern)
    return value.is_true(rubycall.call1(pattern, EQQ, target))


def _binop(frame, recv, arg, mid):
    """Both operands back on the stack, where the mark hook reaches them, before the send that may allocate."""
    frame.push(recv)
    frame.push(arg)
    return _opt_send(frame, mid, 1)


def _unop(frame, recv, mid):
    frame.push(recv)
    return _opt_send(frame, mid, 0)


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


# is_recursive: execute recurses per Ruby call, so an inlining limit must retrace the callee as its own loop instead of leaving a portal call that escapes the virtualizable.
jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'], is_recursive=True,
                      get_printable_location=get_printable_location)


class _Reselection(object):
    """One deliberate reselection: the first traces a program compiles are picked off a cold profile, so they are thrown away once and taken again from a warm one."""
    # Quasi-immutable, so disabling folds the counter below out of every trace.
    _immutable_fields_ = ['enabled?']

    def __init__(self):
        self.enabled = True
        self.count = 0
        self.at = RESELECT_AT


# Late enough that the second selection sees a warm profile, early enough that a benchmark's measured region still runs on it; both ends were measured.
RESELECT_AT = 2000000

reselection = _Reselection()


def configure_reselection():
    """RPYYARV_RESELECT_AT overrides the backward-branch count the reselection fires at; 0 disables it, and a disabled counter folds out of every trace."""
    spec = os.environ.get('RPYYARV_RESELECT_AT')
    if spec is None:
        return
    try:
        at = int(spec)
    except ValueError:
        return
    reselection.at = at
    reselection.enabled = at > 0


def _tick_reselection():
    if reselection.enabled:
        reselection.count += 1
        if reselection.count > reselection.at:
            # Disabling invalidates every compiled trace, which is the reselection.
            reselection.enabled = False


def _epc(iseq, pc):
    """Catch-table ranges are against the pc *after* the raising instruction."""
    return pc + 1 + optable.NUM_OPERANDS[iseq.code[pc]]


def execute(iseq, frame, pc=0):
    """Two shapes on purpose: the handler shape stops the JIT inlining the call, so a catch-free ISeq keeps a plain tail call; iseq is green, so the branch folds away."""
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
    """A frame a `return` inside one of its blocks names; its own ensure entries have run, so what is left is to answer the value (vm_throw_start's valid_return)."""
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
    # No loop here: a loop would keep the tracer from inlining this, and then every call of a rescue/ensure-carrying ISeq escapes its fresh virtualizable and aborts the trace. The unwind loop only runs once something raised.
    gcroots.push_frame(frame)
    try:
        try:
            return _execute(iseq, frame, pc)
        except RubyException, e:
            throw = Throw(PENDING_RAISE, e.value, None, e.name)
        except block_mod.BlockBreak, e:
            throw = Throw(PENDING_BREAK, e.value, e.w_block)
        except block_mod.BlockReturn, e:
            throw = Throw(PENDING_RETURN, e.value, None, 'return', e.frame)
        except block_mod.BlockNext, e:
            throw = Throw(PENDING_NEXT, e.value)
        return _execute_unwinding(iseq, frame, throw)
    finally:
        gcroots.pop_frame(frame)


def _execute_unwinding(iseq, frame, throw):
    while True:
        pc = _unwind(iseq, frame, throw, _epc(iseq, frame.pc))
        try:
            return _execute(iseq, frame, pc)
        except RubyException, e:
            throw = Throw(PENDING_RAISE, e.value, None, e.name)
        except block_mod.BlockBreak, e:
            throw = Throw(PENDING_BREAK, e.value, e.w_block)
        except block_mod.BlockReturn, e:
            throw = Throw(PENDING_RETURN, e.value, None, 'return', e.frame)
        except block_mod.BlockNext, e:
            throw = Throw(PENDING_NEXT, e.value)


def _execute(iseq, frame, pc):
    while True:
        jitdriver.jit_merge_point(iseq=iseq, pc=pc, frame=frame)
        # Only an unwinding exception reads this; a store to a virtualizable field costs a trace nothing.
        frame.pc = pc
        # Rebound each iteration: hoisting it would leave a live variable across the merge point that is neither green nor red.
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
                frame.push(frame.local_get(idx))
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                frame.push(_outer_frame(frame, level).local_get(idx))
        elif opcode == insns.SETLOCAL:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            if packed == idx:
                frame.local_set(idx, frame.pop())
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                _outer_frame(frame, level).local_set(idx, frame.pop())
        elif opcode == insns.GETBLOCKPARAMPROXY:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            if f.block_param_set:
                frame.push(f.local_get(idx))
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
                f.local_set(idx, _to_proc(f.block))
                f.block_param_set = True
            frame.push(f.local_get(idx))
        elif opcode == insns.SETBLOCKPARAM:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            f.local_set(idx, frame.pop())
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
            flag = code[pc + 1]
            pc += 2
            _expand(frame, frame.pop(), n, flag)
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
        elif opcode == insns.TOREGEXP:
            opt = code[pc]
            n = code[pc + 1]
            pc += 2
            at = frame.sp - n
            if at < 0:
                raise UnsupportedOperation(
                    'toregexp with %d part(s) underflows the stack' % n)
            parts = [0] * n
            i = 0
            while i < n:
                parts[i] = frame.stack[at + i]
                i += 1
            regexp = boot.toregexp(opt, parts)
            _drop(frame, at)
            frame.push(regexp)
        elif opcode == insns.INTERN:
            frame.push(boot.str_intern(frame.pop()))
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
        elif opcode == insns.ONCE:
            idx = code[pc]
            pc += 1
            v = iseq.once_cache[idx]
            if v == value.Q_UNDEF:
                v = _run_once(frame, iseq, idx)
            frame.push(v)
        elif opcode == insns.GETCLASSVARIABLE:
            mid = code[pc]
            pc += 1
            frame.push(_cvar_get(_cref_of(frame), mid))
        elif opcode == insns.SETCLASSVARIABLE:
            mid = code[pc]
            pc += 1
            _cvar_set(_cref_of(frame), mid, frame.pop())
        elif opcode == insns.DEFINED:
            kind = code[pc]
            obj = iseq.consts[code[pc + 1]]
            pushval = iseq.consts[code[pc + 2]]
            pc += 3
            recv = frame.pop()
            frame.push(pushval if _defined(frame, kind, obj, recv)
                       else value.Q_NIL)
        elif opcode == insns.DEFINEDIVAR:
            mid = code[pc]
            pushval = iseq.consts[code[pc + 1]]
            pc += 2
            frame.push(pushval if boot.ivar_defined(
                frame.self_val, rubycall.rid(mid)) else value.Q_NIL)
        elif opcode == insns.GETCONSTANT:
            mid = code[pc]
            pc += 1
            allow_nil = frame.pop()
            cbase = frame.pop()
            if allow_nil == value.Q_TRUE and cbase == value.Q_NIL:
                frame.push(_const_lexical(_cref_of(frame), mid))
            else:
                frame.push(dispatch.const_get(cbase, mid))
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
            frame.push(_const_path(frame, iseq, idx))
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
            kind = flags & optable.DEFINECLASS_TYPE_MASK
            if kind == optable.DEFINECLASS_TYPE_SINGLETON_CLASS:
                frame.push(_definesingletonclass(frame, w_body, cbase))
            else:
                frame.push(_defineclass(
                    frame, mid, w_body, cbase, super_v,
                    kind == optable.DEFINECLASS_TYPE_MODULE))
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
                # Receiver of the `initialize` send that follows, and the slot below it, which becomes that send's result.
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
            dispatch.define_singleton(frame.pop(), mid, w_body,
                                      _const_base(frame), _cref_of(frame))
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
                _tick_reselection()
                jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHIF:
            target = code[pc]
            pc += 1
            if value.is_true(frame.pop()):
                backward = target < pc
                pc = target
                if backward:
                    _tick_reselection()
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHUNLESS:
            target = code[pc]
            pc += 1
            if not value.is_true(frame.pop()):
                backward = target < pc
                pc = target
                if backward:
                    _tick_reselection()
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHNIL:
            target = code[pc]
            pc += 1
            if frame.pop() == value.Q_NIL:
                backward = target < pc
                pc = target
                if backward:
                    _tick_reselection()
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.CHECKMATCH:
            flag = code[pc]
            pc += 1
            pattern = frame.pop()
            target = frame.pop()
            frame.push(_checkmatch(target, pattern, flag))
        elif opcode == insns.CHECKKEYWORD:
            idx = code[pc]
            bit = code[pc + 1]
            pc += 2
            assert idx >= 0
            # A set bit means the optional went unfilled, so vm_check_keyword answers false and the body computes its default.
            frame.push(value.newbool(
                (value.fix2int(frame.local_get(idx)) & (1 << bit)) == 0))
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
        elif opcode == insns.GETSPECIAL:
            key = code[pc]
            type = code[pc + 1]
            pc += 2
            assert key == 1
            frame.push(boot.getspecial(type))
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
            v = helpers.lshift(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.LTLT))
        elif opcode == insns.OPT_NIL_P:
            recv = frame.pop()
            v = helpers.nil_p(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.NIL_P))
        elif opcode == insns.OPT_SUCC:
            recv = frame.pop()
            v = helpers.add(recv, value.int2fix(1))
            frame.push(v if v != value.Q_UNDEF else _unop(frame, recv, SUCC))
        elif opcode == insns.OPT_STR_FREEZE:
            idx = code[pc]
            pc += 1
            v_str = iseq.consts[idx]
            if helpers.str_freeze_pristine():
                frame.push(v_str)
            else:
                frame.push(_unop(frame, rubycall.call0(v_str, DUP),
                                 helpers.FREEZE))
        elif opcode == insns.OPT_STR_UMINUS:
            idx = code[pc]
            pc += 1
            v_str = iseq.consts[idx]
            v = helpers.str_uminus(v_str)
            if v != value.Q_UNDEF:
                frame.push(v)
            else:
                frame.push(_unop(frame, v_str, helpers.UMINUS))
        elif opcode == insns.OPT_ARY_FREEZE or \
                opcode == insns.OPT_HASH_FREEZE:
            idx = code[pc]
            pc += 1
            frame.push(_unop(frame, rubycall.call0(iseq.consts[idx], DUP),
                             helpers.FREEZE))
        elif opcode == insns.OPT_CASE_DISPATCH:
            table = code[pc]
            else_pc = code[pc + 1]
            pc += 2
            key = frame.pop()
            if value.is_fixnum(key) and helpers.int_eqq_pristine():
                target = iseq.case_tables[table].get(value.fix2int(key), -1)
                pc = else_pc if target < 0 else target
        elif opcode == insns.OPT_NEWARRAY_SEND:
            n = code[pc]
            meth = code[pc + 1]
            pc += 2
            frame.push(_newarray_send(frame, n, meth))
        elif opcode == insns.PUSHTOARRAY:
            n = code[pc]
            pc += 1
            _pushtoarray(frame, n)
        elif opcode == insns.CONCATARRAY or opcode == insns.CONCATTOARRAY:
            b = frame.pop()
            a = frame.pop()
            frame.push(rubycall.concat_array(
                a, b, opcode == insns.CONCATTOARRAY))
        elif opcode == insns.OPT_REGEXPMATCH2:
            b = frame.pop()
            a = frame.pop()
            frame.push(_binop(frame, a, b, MATCH))
        elif opcode == insns.OPT_DUPARRAY_SEND:
            idx = code[pc]
            mid = code[pc + 1]
            pc += 3
            arg = frame.pop()
            frame.push(rubycall.call1(
                rubycall.ary_resurrect(iseq.consts[idx]), mid, arg))
        else:
            raise UnsupportedOperation('unknown opcode %d' % opcode)


def run(iseq):
    debug.dump_iseq(iseq)
    ret = execute(iseq, Frame(iseq, boot.top_self()))
    debug.summary()
    return ret


def run_in_cruby():
    """The whole script handed back because some ISeq in it is one RPyYARV cannot represent; cleans up too, so its answer is the exit status."""
    return boot.run_node()
