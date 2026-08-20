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
    """Lexical scope chained as CRuby's rb_cref_t; klass 0 is Object."""
    _immutable_fields_ = ['klass', 'outer', 'by_eval', 'const_base']

    def __init__(self, klass, outer, by_eval=False):
        self.klass = klass
        self.outer = outer
        # CREF_PUSHED_BY_EVAL: a def lands here, but const lookup steps over it.
        self.by_eval = by_eval
        # Resolved once: _const_base is on every constant read's hot path.
        if by_eval and outer is not None:
            self.const_base = outer.const_base
        else:
            self.const_base = klass
        # klass -> Cref: a re-run class body reuses the node const guards hold.
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
    """Const-resolution scope chain; a method frame uses its entry's."""
    c = frame.cref
    if c is None:
        entry = frame.entry
        if entry is not None:
            c = entry.lexical
    if c is None:
        return TOP_CREF
    return c


def define_method(frame, mid, w_iseq):
    """A def in a class body lands on it; a toplevel def is private."""
    node = frame.cref
    if node is None:
        dispatch.define(value.core_class(value.C_OBJECT), mid, w_iseq, True,
                        0, _cref_of(frame))
    elif frame.module_func:
        dispatch.define(node.klass, mid, w_iseq, True, node.klass, node)
        dispatch.define_singleton(node.klass, mid, w_iseq, node.klass, node)
    else:
        dispatch.define(node.klass, mid, w_iseq, frame.private_pragma,
                        node.klass, node)


@unroll_safe
def invoke(frame, w_ci, w_block=None):
    if w_ci.blockarg:
        # Read before pop, so frame marks it across the alloc (vm_args.c:1119).
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
        # Green, so this store is only in the trace of a real such site.
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
    # Promoted: the class-word guard is the inline cache; lookup folds away.
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
            return _attr_send(frame, entry, recv, recv_at, argc, w_block)
        callee_iseq = entry.w_iseq

    if callee_iseq is not None:
        if w_block is None or w_ci.blockarg:
            # A break unwinds to the send the block was written at.
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
    if entry is None and argc == 0 and w_block is None and mid == ALLOCATE \
            and not value.is_immediate(recv) \
            and send_owners.class_allocate != 0 \
            and dispatch.owner_of(klass, ALLOCATE) == \
            send_owners.class_allocate:
        v = boot.alloc_default(recv)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 and w_block is None \
            and mid == FORCE_ENCODING \
            and send_owners.string_force_encoding != 0 \
            and dispatch.owner_of(klass, FORCE_ENCODING) == \
            send_owners.string_force_encoding:
        v = boot.str_force_encoding_fast(recv, frame.stack[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 and w_block is None and mid == UNPACK1 \
            and send_owners.string_unpack1 != 0 \
            and dispatch.owner_of(klass, UNPACK1) == \
            send_owners.string_unpack1:
        v = boot.unpack1_double(recv, frame.stack[recv_at + 1],
                                value.int2fix(0))
        if v != value.Q_UNDEF:
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
    if entry is None and argc == 0 and mid == helpers.LAST_MATCH \
            and regexp_class.value != 0 and recv == regexp_class.value:
        v = helpers.last_match0()
        _drop(frame, recv_at)
        debug.count_native()
        return v
    if entry is None and argc == 1 and mid == helpers.LAST_MATCH \
            and regexp_class.value != 0 and recv == regexp_class.value:
        v = helpers.last_match1(frame.stack[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 and mid == helpers.ESCAPE_HTML_MID \
            and recv == dispatch.const_at(value.core_class(value.C_OBJECT),
                                          CGI_CONST):
        # const_at is Qundef until cgi/escape defines CGI: an elidable miss.
        v = helpers.cgi_escape_html(frame.stack[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and mid == helpers.BYTESLICE:
        v = helpers.str_byteslice(recv, frame.stack[recv_at + 1],
                                  frame.stack[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and mid == helpers.TR:
        v = helpers.str_tr(recv, frame.stack[recv_at + 1],
                           frame.stack[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and w_block is None \
            and (mid == helpers.GSUB or mid == helpers.GSUB_BANG
                 or mid == helpers.SUB or mid == helpers.SUB_BANG):
        v = helpers.str_gsub2(recv, frame.stack[recv_at + 1],
                              frame.stack[recv_at + 2], mid)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and fcall and w_block is None and argc >= 2 \
            and argc - 1 <= boot.MAX_ARGC \
            and (mid == helpers.FORMAT_MID or mid == helpers.SPRINTF_MID):
        fmt = frame.stack[recv_at + 1]
        args = []
        i = 0
        while i < argc - 1:
            args.append(frame.stack[recv_at + 2 + i])
            i += 1
        v = helpers.kernel_format(recv, fmt, args, mid)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 and w_block is None \
            and mid == helpers.MATCH_MID:
        v = helpers.str_match(recv, frame.stack[recv_at + 1])
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
            _eval_receiver(recv):
        v = _module_eval_rpy(frame, recv, frame.stack[recv_at + 1],
                             frame.stack[recv_at + 2] if argc >= 2
                             else value.Q_NIL,
                             frame.stack[recv_at + 3] if argc >= 3 else 0)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    # &proc too: out through CRuby the def would land on the proc's cref.
    if w_block is not None and entry is None and argc == 0 \
            and (mid == CLASS_EVAL or mid == MODULE_EVAL) \
            and w_block.kind == block_mod.KIND_ISEQ \
            and dispatch.owner_of(klass, mid) == \
            value.core_class(value.C_MODULE) \
            and _eval_receiver(recv):
        return _module_eval_block(frame, recv, recv_at, w_block)
    if _is_attr_mid(mid) and argc > 0 and not value.is_immediate(recv) \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)):
        return _define_attrs(frame, mid, recv, recv_at, argc)
    if mid == DEFINE_METHOD and argc == 1 and not w_ci.blockarg \
            and w_block is not None and w_block.kind == block_mod.KIND_ISEQ \
            and w_block.w_iseq.simple_params and not frame.module_func \
            and _attr_name(frame.stack[recv_at + 1]) != '':
        return _define_bmethod(frame, mid, recv, recv_at, w_block,
                               frame.private_pragma)
    if mid == DEFINE_METHOD and argc == 1 and frame.module_func \
            and _attr_name(frame.stack[recv_at + 1]) != '':
        # CRuby's send never learns RPyYARV's module_function pragma.
        return _define_bmethod_modfunc(frame, mid, recv, recv_at, w_block)
    if mid == INITIALIZE and argc == 0 and entry is None and w_block is None \
            and helpers.basic_initialize(klass):
        # rb_obj_dummy_initialize: no argument, no effect, nil (object.c:118).
        _drop(frame, recv_at)
        debug.count_native()
        return value.Q_NIL
    if mid == BLOCK_GIVEN and fcall and argc == 0:
        # rb_funcallv would give rb_f_block_given_p a CRuby caller (vm.c:1862).
        _drop(frame, recv_at)
        return value.newbool(frame.block is not None)
    if (mid == METHOD_UNDERSCORE or mid == CALLEE_UNDERSCORE) \
            and fcall and argc == 0 and entry is None:
        # rb_f_method_name reads the running CRuby frame; RPyYARV pushes none.
        _drop(frame, recv_at)
        debug.count_native()
        return _running_method(frame)
    if mid == BACKTRACE_PRIM and fcall and argc == 0:
        _drop(frame, recv_at)
        debug.count_native()
        return _backtrace()
    if mid == REQUIRE_PRIM and fcall and argc == 1:
        # A require CRuby dispatched (autoload) reaches RPyYARV only here.
        v = rubycall.hooks.require.from_cruby(frame.stack[recv_at + 1])
        _drop(frame, recv_at)
        return v
    if mid == HASH_PAIRS_PRIM and fcall and argc == 1 \
            and boot.is_hash(frame.stack[recv_at + 1]):
        v = boot.hash_pairs(frame.stack[recv_at + 1])
        _drop(frame, recv_at)
        debug.count_native()
        return v
    if mid == DIR_UNDERSCORE and fcall and argc == 0:
        # f_dir: the running file is this frame's ISeq, not a CRuby frame's.
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
    if w_block is not None and mid == EACH_WITH_INDEX and argc == 0 and \
            entry is None and value.is_plain_array(recv) and \
            dispatch.owner_of(klass, EACH_WITH_INDEX) == \
            send_owners.array_each_with_index:
        _drop(frame, recv_at)
        try:
            return _array_each_with_index(recv, w_block)
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
        # A Proc RPyYARV made: run its block here, not out through CRuby.
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
        # rb_funcall_with_block would wrap a handle that dies with the call.
        _drop(frame, recv_at)
        debug.count_native()
        if mid == CORE_LAMBDA:
            return _to_proc(block_mod.W_Block(
                w_block.w_iseq, w_block.frame, w_block.outer, is_lambda=True))
        return _to_proc(w_block)
    if mid == MODULE_FUNCTION and fcall \
            and (_in_body_of(frame, recv)
                 or (argc > 0 and dispatch.is_known_module(recv))):
        # With names it works from a method body; registry mirrors singletons.
        return _module_function(frame, recv, recv_at, argc)
    if mid == PRIVATE_CLASS_METHOD and argc > 0 \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)):
        return _private_class_method(frame, recv, recv_at, argc)
    if (mid == PRIVATE or mid == PUBLIC) and fcall and argc == 0 \
            and _in_body_of(frame, recv):
        return _visibility_pragma(frame, mid, recv, recv_at)
    if (mid == PRIVATE or mid == PUBLIC) and fcall and argc > 0 \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)):
        return _visibility_names(frame, mid, recv, recv_at, argc)
    if (mid == REMOVE_METHOD or mid == UNDEF_METHOD) and argc > 0 \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)):
        return _remove_or_undef(frame, mid, recv, recv_at, argc)
    if mid == RUBY2_KEYWORDS and fcall and argc == 1 \
            and (dispatch.is_known_class(recv)
                 or dispatch.is_known_module(recv)):
        v = _ruby2_keywords(frame, recv, recv_at)
        if v != value.Q_UNDEF:
            return v
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
            # `->`: the block re-tagged as a lambda, over a persistent handle.
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
            # Only the send the block was written at catches it.
            if e.w_block is not w_block:
                raise
            return e.value
    # Entry survives only as private to a receiverless call (CALL_FCALL).
    public_only = entry is not None and not fcall
    if not debug.state.enabled:
        ret = rubycall.call(recv, mid, args, public_only)
        # A Proc of ours cannot raise through libruby's frames; it parked.
        _check_block_error()
        return ret
    debug.trace_enter(mid, args)
    ret = rubycall.call(recv, mid, args, public_only)
    _check_block_error()
    debug.trace_leave(mid, ret)
    return ret


# Above this, back to CRuby: the loop is traced, not a jitdriver.
ARY_NEW_BLOCK_MAX = 64

# rb_ary_resize nil-fills; past this the second pass costs more.
ARY_NEW_FILL_MAX = 128


@dont_look_inside
def _array_new(size, fill, argc):
    """rb_ary_s_new for a direct Array (array.c:1071); Qundef otherwise."""
    # Out of line: inlining these grew cd's and havlak's traces ~5%.
    if argc > 2:
        return value.Q_UNDEF
    if argc == 0:
        return rubycall.ary_new_capa(0)
    # FIXNUM_P: to_int, to_ary and Bignum take rb_ary_initialize's slow paths.
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
    """Traced through: an enclosing-local read forces caller's virtualizable."""
    # argc 0 and argc 2 are rb_warning cases in rb_ary_initialize.
    if argc != 1:
        return value.Q_UNDEF
    size = frame.stack[recv_at + 1]
    if not value.is_fixnum(size):
        return value.Q_UNDEF
    n = value.fix2int(size)
    if n < 0 or n > ARY_NEW_BLOCK_MAX:
        return value.Q_UNDEF
    ary = rubycall.ary_new_capa(n)
    # Into the receiver's slot: the frame marks it, nothing else holds it.
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
    """Enumerable#each_slice for a plain Array, no CRuby callback per slice."""
    at = 0
    while at < value.ary_len(ary):
        remaining = value.ary_len(ary) - at
        count = size if size < remaining else remaining
        part = boot.ary_subseq(ary, at, count)
        call_block(w_block, [part])
        at += count
    return ary


def _array_each_with_index(ary, w_block):
    """Enumerable#each_with_index for a plain Array, no CRuby per element."""
    i = 0
    # Length re-read each pass: mutation mid-iteration behaves like CRuby.
    while i < value.ary_len(ary):
        call_block(w_block, [value.ary_at(ary, i), value.int2fix(i)])
        i += 1
    return ary


NEW = symbols.intern('new')
INITIALIZE = symbols.intern('initialize')
BLOCK_GIVEN = symbols.intern('block_given?')
DIR_UNDERSCORE = symbols.intern('__dir__')
BACKTRACE_PRIM = symbols.intern('__rpyyarv_backtrace__')
HASH_PAIRS_PRIM = symbols.intern('__rpyyarv_hash_pairs__')
REQUIRE_PRIM = symbols.intern('__rpyyarv_require__')
METHOD_UNDERSCORE = symbols.intern('__method__')
CALLEE_UNDERSCORE = symbols.intern('__callee__')


# A deeper chain than this is a runaway; caller only ever reads the top anyway.
MAX_BACKTRACE = 4096
# What InstructionSequence.compile names a fileless source (prelude.rb).
COMPILED_PATH = '<compiled>'


def _running_method(frame):
    """__method__: the innermost method frame's entry; nil at the toplevel."""
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
    """path, line and label of every live RPyYARV frame, innermost first."""
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
    """__dir__ for this frame's ISeq file; Qundef when it has none."""
    path = frame.w_iseq.path
    if path == '' or path.startswith('<'):
        return value.Q_UNDEF
    return boot.dir_of(boot.str_new(path))
ITSELF = symbols.intern('itself')
REVERSE_EACH = symbols.intern('reverse_each')
EACH_SLICE = symbols.intern('each_slice')
EACH_WITH_INDEX = symbols.intern('each_with_index')
INDEX = symbols.intern('index')
SUCC = symbols.intern('succ')
BUFFER = symbols.intern('buffer')
GETBYTE = symbols.intern('getbyte')
SETBYTE = symbols.intern('setbyte')
ALLOCATE = symbols.intern('allocate')
FORCE_ENCODING = symbols.intern('force_encoding')
UNPACK1 = symbols.intern('unpack1')
OFFSET = symbols.intern('offset')

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
DEFINE_METHOD = symbols.intern('define_method')


def _is_attr_mid(mid):
    return (mid == ATTR_READER or mid == ATTR_WRITER
            or mid == ATTR_ACCESSOR)


SEND = symbols.intern('send')
SEND2 = symbols.intern('__send__')
# opt_regexpmatch2 falls through to this send; CRuby sets $~ there.
MATCH = symbols.intern('=~')


class _SendOwners(object):
    # Quasi-immutable: install() writes it once, before any Ruby code runs.
    _immutable_fields_ = ['kernel?', 'basic?', 'string_getbyte?',
                          'string_setbyte?', 'array_each_slice?',
                          'array_each_with_index?',
                          'comparable?', 'class_allocate?',
                          'string_force_encoding?', 'string_unpack1?',
                          'array_pack?']

    def __init__(self):
        self.kernel = 0
        self.basic = 0
        self.eval = 0
        self.string_getbyte = 0
        self.string_setbyte = 0
        self.array_each_slice = 0
        self.array_each_with_index = 0
        self.comparable = 0
        self.class_allocate = 0
        self.string_force_encoding = 0
        self.string_unpack1 = 0
        self.array_pack = 0


# Kernel#send and BasicObject#__send__, so an override of either is seen.
send_owners = _SendOwners()


def _send_target(frame, klass, mid, argc, recv_at):
    if argc < 1:
        return rubycall.NO_MID
    return _send_target_of(klass, mid, frame.stack[recv_at + 1])


def _send_target_of(klass, mid, name):
    """vm_call_opt_send: the method a send names, or NO_MID if not pristine."""
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
    """rb_check_id of a send's first argument (vm_eval.c:1245)."""
    if boot.is_symbol(v):
        return symbols.intern(boot.sym_of(v))
    if not value.is_immediate(v) and boot.is_string(v):
        return symbols.intern(boot.str_of(v))
    return rubycall.NO_MID


@unroll_safe
def _shift_off(frame, recv_at):
    """Drop a send's method-name argument, closing the gap under recv."""
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
        v = helpers.reg_eqq(recv, arg)
        if v != value.Q_UNDEF:
            return v
        return helpers.mod_eqq(recv, arg)
    if mid == MATCH:
        return helpers.str_eq_tilde(recv, arg)
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
    if mid == helpers.UNSHIFT_MID:
        return helpers.ary_unshift1(recv, arg)
    if mid == helpers.SKIP_MID:
        return helpers.ss_skip(recv, arg)
    if mid == helpers.POS_SET:
        return helpers.ss_set_pos(recv, arg)
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


@unroll_safe
def _attr_send(frame, entry, recv, recv_at, argc, w_block=None):
    """attr_* entry: getinstancevariable's ivar access, without a frame."""
    if entry.kind == dispatch.KIND_BMETHOD:
        args = [0] * argc
        i = 0
        while i < argc:
            args[i] = frame.stack[recv_at + 1 + i]
            i += 1
        _drop(frame, recv_at)
        # A block here must reach a yield in the body: left to CRuby's bmethod.
        if w_block is not None:
            return _call_with_block(recv, entry.mid, args, w_block)
        debug.count_native()
        return _run_bmethod(entry.w_block, recv, args)
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
    private = frame.private_pragma
    if private:
        # CRuby's send never learns RPyYARV's private pragma: make them private.
        names = _attr_method_names(mid, args)
        if len(names) > 0:
            rubycall.call(klass, PRIVATE, names)
    _install_attrs(klass, mid, args, private)
    return ret


def _attr_method_names(mid, args):
    names = []
    for i in range(len(args)):
        name = _attr_name(args[i])
        if name == '':
            continue
        if mid != ATTR_WRITER:
            names.append(rubycall.sym_value(symbols.intern(name)))
        if mid != ATTR_READER:
            names.append(rubycall.sym_value(symbols.intern(name + '=')))
    return names


@dont_look_inside
def _install_attrs(klass, mid, args, private=False):
    """attr_* still runs in CRuby; the registry gains native entries too."""
    for i in range(len(args)):
        name = _attr_name(args[i])
        if name == '':
            continue
        ivar = symbols.intern('@' + name)
        if mid != ATTR_WRITER:
            dispatch.define_attr(klass, symbols.intern(name), ivar,
                                 dispatch.KIND_ATTR_READER, private)
        if mid != ATTR_READER:
            dispatch.define_attr(klass, symbols.intern(name + '='), ivar,
                                 dispatch.KIND_ATTR_WRITER, private)


def _attr_name(v):
    if boot.is_symbol(v):
        return boot.sym_of(v)
    if not value.is_immediate(v) and boot.is_string(v):
        return boot.str_of(v)
    return ''


def _is_class_or_module(v):
    if value.is_immediate(v):
        return False
    kind = raw_word(v, value.FLAGS_WORD) & value.T_MASK
    return kind == value.T_CLASS or kind == value.T_MODULE


@unroll_safe
def _define_bmethod(frame, mid, recv, recv_at, w_block, private_pragma=False):
    """define_method: CRuby installs the real bmethod, plus a fast entry."""
    name_v = frame.stack[recv_at + 1]
    _drop(frame, recv_at)
    # First, so a name or block CRuby rejects raises before registering.
    ret = _call_with_block(recv, mid, [name_v], w_block)
    # A Symbol is a CRuby immediate: no is_immediate guard needed.
    if not boot.is_symbol(ret):
        return ret
    returned_mid = symbols.intern(boot.sym_of(ret))
    # recv is the class for `class C; define_method`, its class at toplevel.
    search = recv if _is_class_or_module(recv) else value.class_of(recv)
    if value.is_immediate(search):
        return ret
    owner = dispatch.owner_of(search, returned_mid)
    if value.is_immediate(owner) or owner == value.Q_NIL:
        return ret
    if private_pragma:
        # CRuby's send never learns RPyYARV's private pragma: make it private.
        rubycall.call(owner, PRIVATE, [ret])
    # is_lambda is quasi-immutable: flag once here, never mutate later.
    lambda_block = block_mod.W_Block(w_block.w_iseq, w_block.frame,
                                     w_block.outer, is_lambda=True)
    dispatch.define_bmethod(owner, returned_mid, lambda_block,
                            frame.cref is None or private_pragma)
    return ret


@unroll_safe
def _define_bmethod_modfunc(frame, mid, recv, recv_at, w_block):
    """define_method under module_function: private plus a singleton copy."""
    name_v = frame.stack[recv_at + 1]
    _drop(frame, recv_at)
    ret = _call_with_block(recv, mid, [name_v], w_block)
    if not boot.is_symbol(ret):
        return ret
    rubycall.call(recv, MODULE_FUNCTION, [ret])
    returned_mid = symbols.intern(boot.sym_of(ret))
    lambda_block = block_mod.W_Block(w_block.w_iseq, w_block.frame,
                                     w_block.outer, is_lambda=True)
    dispatch.define_bmethod(recv, returned_mid, lambda_block, True)
    dispatch.define_singleton_bmethod(recv, returned_mid, lambda_block)
    return ret


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
def _eval_receiver(recv):
    """Out through CRuby a string eval's defs would lose their cref home."""
    if dispatch.is_known_class(recv) or dispatch.is_known_module(recv):
        return True
    if value.is_immediate(recv):
        return False
    kind = raw_word(recv, value.FLAGS_WORD) & value.T_MASK
    if kind != value.T_CLASS and kind != value.T_MODULE:
        return False
    dispatch.adopt(recv)
    return True


def _module_eval_rpy(frame, recv, source, file_v, line_v):
    """String class_eval/module_eval keeping the caller's lexical CREF."""
    if value.is_immediate(source) or not boot.is_string(source):
        return value.Q_UNDEF
    from rpyyarv import bootiseq
    from rpyyarv import loader
    text = boot.str_of(source)
    line = value.fix2int(line_v) if value.is_fixnum(line_v) else 1
    names = _eval_local_names(frame, text)
    if len(names) > 0:
        # eval_string_with_cref runs in the caller's scope: declare its locals.
        text = _declare_locals(names) + text
        line -= 1
    try:
        iseqw = _compile_eval(text, file_v, line)
        gcroots.hold(iseqw)
        try:
            result = loader.load(bootiseq.load(iseqw))
        finally:
            gcroots.release(iseqw)
    except RubyException:
        return value.Q_UNDEF
    except RPyYarvError:
        return value.Q_UNDEF
    if len(result.reasons) > 0:
        return value.Q_UNDEF
    # Not by_eval: eval_under pushes the receiver's cref (vm_eval.c:2269).
    cref = _push_cref(_cref_of(frame), recv)
    callee = Frame(result.w_iseq, recv, cref, frame.entry)
    _copy_eval_locals(frame, callee, result.w_iseq, False)
    try:
        return execute(result.w_iseq, callee)
    finally:
        # ponytail: locals copied in/out; share the env if a Proc must see them.
        _copy_eval_locals(frame, callee, result.w_iseq, True)


COMPILE = symbols.intern('compile')


@dont_look_inside
def _compile_eval(text, file_v, line):
    """Compile eval source at the caller's file and line, for __FILE__."""
    rubyvm = boot.const_get(value.core_class(value.C_OBJECT),
                            boot.intern('RubyVM'))
    iseq_class = boot.const_get(rubyvm, boot.intern('InstructionSequence'))
    src = boot.str_new(text)
    gcroots.hold(src)
    try:
        return boot.funcallv(iseq_class, boot.intern('compile'),
                             [src, file_v, file_v, value.int2fix(line)],
                             COMPILE)
    finally:
        gcroots.release(src)


def _is_local_name(name):
    """A name the eval source may declare; `_1` and `it` are the parser's."""
    if len(name) == 0 or name == 'it':
        return False
    c = name[0]
    if not ((c >= 'a' and c <= 'z') or c == '_'):
        return False
    i = 1
    while i < len(name):
        c = name[i]
        if not ((c >= 'a' and c <= 'z') or (c >= 'A' and c <= 'Z')
                or (c >= '0' and c <= '9') or c == '_'):
            return False
        i += 1
    return not (len(name) == 2 and name[0] == '_'
                and name[1] >= '0' and name[1] <= '9')


def _eval_local_names(frame, text):
    """Every local the string names, innermost first, out to the method's."""
    names = []
    seen = {}
    f = frame
    n = 0
    while f is not None and n < MAX_SCOPES:
        for name in f.w_iseq.local_names:
            if _is_local_name(name) and name not in seen \
                    and text.find(name) >= 0:
                seen[name] = True
                names.append(name)
        f = f.defining_frame
        n += 1
    return names


def _declare_locals(names):
    parts = []
    for name in names:
        parts.append('%s = %s' % (name, name))
    return '; '.join(parts) + '\n'


def _copy_eval_locals(frame, callee, w_iseq, back):
    """Caller locals in and back out, so an assignment reaches the caller."""
    f = frame
    n = 0
    seen = {}
    while f is not None and n < MAX_SCOPES:
        names = f.w_iseq.local_names
        i = 0
        while i < len(names):
            name = names[i]
            if _is_local_name(name) and name not in seen:
                seen[name] = True
                at = _slot_named(w_iseq, name)
                if at >= 0:
                    if back:
                        f.local_set(i, callee.local_get(at))
                    else:
                        callee.local_set(at, f.local_get(i))
            i += 1
        f = f.defining_frame
        n += 1


def _slot_named(w_iseq, name):
    names = w_iseq.local_names
    i = 0
    while i < len(names):
        if names[i] == name:
            return i
        i += 1
    return -1


def _new_with_block(frame, entry, klass, recv_at, argc, w_block):
    """Klass.new { }: CRuby's Class#new gives initialize a dying handle."""
    obj = dispatch.alloc(klass)
    # Into the caller's marked slot; _enter drops it after placing args.
    frame.stack[recv_at] = obj
    _enter(frame, entry, obj, recv_at, argc, INITIALIZE, w_block)
    return obj


@unroll_safe
def _kw_splat_hash(frame, at):
    """vm_caller_setup_keyword_hash: to_hash first; nil means no keywords."""
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
    """A send with VM_CALL_KWARG keywords or a VM_CALL_KW_SPLAT Hash on top."""
    if w_ci.kw_splat:
        _kw_splat_hash(frame, recv_at + argc)
    if w_ci.splat:
        return _splat_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall)
    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    klass = promote(value.class_of(recv))
    # Keywords stay topmost, so only the name below them is shifted off.
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
            # attr_* takes no keywords: only the arity error CRuby raises.
            return _attr_send(frame, entry, recv, recv_at, argc, w_block)
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
    # String#unpack1's one keyword shape, without building the Hash.
    if entry is None and w_block is None and argc == 2 and mid == UNPACK1 \
            and len(w_ci.kw_names) == 1 and w_ci.kw_names[0] == OFFSET \
            and send_owners.string_unpack1 != 0 \
            and dispatch.owner_of(klass, UNPACK1) == \
            send_owners.string_unpack1:
        v = boot.unpack1_double(recv, frame.stack[recv_at + 1],
                                frame.stack[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    # protoboeuf's encoder packs with this shape; no Hash built.
    if entry is None and w_block is None and argc == 2 \
            and mid == helpers.PACK \
            and len(w_ci.kw_names) == 1 and w_ci.kw_names[0] == BUFFER \
            and send_owners.array_pack != 0 \
            and dispatch.owner_of(klass, helpers.PACK) == \
            send_owners.array_pack:
        v = boot.pack_double_into(recv, frame.stack[recv_at + 1],
                                  frame.stack[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    # A block RPyYARV holds runs here, keywords never crossing libruby.
    if proxy.value != 0 and recv == proxy.value:
        return _block_send(frame, mid, recv_at, argc, frame.block,
                           w_ci.kw_names, w_ci.kw_splat)
    if len(blocks.by_proc) > 0 and _is_proxy_call(mid) \
            and recv in blocks.by_proc:
        return _block_send(frame, mid, recv_at, argc, blocks.by_proc[recv],
                           w_ci.kw_names, w_ci.kw_splat)
    # Left in the marked frame until rb_hash_aset has copied each one.
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
        # Resolved first: rb_intern allocates, an RPython list is no GC root.
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
            # Only the send the block was written at catches it.
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
    """A *splat call's args as a list; the Array stays on the marked stack."""
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
        # Read in place: a call per element would force the virtualizable.
        n = promote(value.ary_len(ary))
        i = 0
        while i < n:
            args.append(value.ary_at(ary, i))
            i += 1
        return _splat_trailing(frame, args, at, npos, trailing)
    # Promoted: a fixed-size args list is one the trace can keep virtual.
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


def _splat_kw(args, kw_splat, trailing):
    """A ruby2_keywords-flagged trailing Hash turns a splat call into kw."""
    if kw_splat or trailing != 0 or len(args) == 0:
        return kw_splat
    return boot.kw_hash_p(args[len(args) - 1])


@unroll_safe
def _splat_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall):
    """A *splat call; the expansion may outrun the frame's sized stack."""
    assert recv_at >= 0
    kw_names = w_ci.kw_names
    nkw = len(kw_names)
    trailing = 1 if w_ci.kw_splat else nkw
    args = _splat_args(frame, recv_at + 1, argc - trailing, trailing)
    kw_splat = _splat_kw(args, w_ci.kw_splat, trailing)
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
            return _attr_send_args(frame, entry, recv, recv_at, args, w_block)
        if w_block is None or w_ci.blockarg:
            return _enter_args(frame, entry, recv, recv_at, args, mid,
                               w_block, kw_names, kw_splat)
        try:
            return _enter_args(frame, entry, recv, recv_at, args, mid,
                               w_block, kw_names, kw_splat)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value
    if proxy.value != 0 and recv == proxy.value:
        _drop(frame, recv_at)
        return _block_send_args(mid, frame.block, args, kw_names,
                                kw_splat)
    if len(blocks.by_proc) > 0 and _is_proxy_call(mid) \
            and recv in blocks.by_proc:
        w_proc = blocks.by_proc[recv]
        _drop(frame, recv_at)
        return _block_send_args(mid, w_proc, args, kw_names, kw_splat)
    # Built while the arguments are still on the marked stack.
    pass_kw = kw_splat or nkw > 0
    if kw_splat:
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


def _attr_send_args(frame, entry, recv, recv_at, args, w_block=None):
    """_attr_send for a *splat call, whose arguments are already a list."""
    argc = len(args)
    if entry.kind == dispatch.KIND_BMETHOD:
        _drop(frame, recv_at)
        if w_block is not None:
            return _call_with_block(recv, entry.mid, args, w_block)
        debug.count_native()
        return _run_bmethod(entry.w_block, recv, args)
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
    """_enter for a *splat call; the caller's stack holds the Array still."""
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
        # Copied out: the codewriter refuses a virtualizable array passed on.
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
    """setup_parameters_complex; answers the opt table's pc (vm_args.c:906)."""
    nkw = len(kw_names)
    takes_kw = len(w_iseq.kw_table) > 0 or w_iseq.kwrest >= 0
    held_flagged = 0
    held_ary = 0
    # A **splat's Hash is the last argument; empty vanishes (vm_args.c:673).
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
        if w_iseq.r2k and not takes_kw and not empty:
            # ruby2_keywords: the kw hash rides the rest array, flagged.
            end = len(args) - 1
            assert end >= 0
            flagged = boot.kw_hash_dup(args[end])
            # Fresh, and an RPython list is no GC root: held until bound.
            gcroots.hold(flagged)
            held_flagged = flagged
            args = args[:end]
            args.append(flagged)
    # No kw params: CRuby folds them to a trailing Hash (args_kw_argv_to_hash).
    fold = nkw > 0 and not takes_kw
    lead = w_iseq.nparams
    opt_num = len(w_iseq.opt_table) - 1
    if opt_num < 0:
        opt_num = 0
    post_num = w_iseq.post_num
    rest = w_iseq.rest_start
    post_start = w_iseq.post_start
    # Restated so the codewriter sees every index as non-negative.
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

    # After the arity check: nothing may raise between hold and release.
    kw_hash = 0
    if fold:
        args = _kw_to_positional(args, kw_names)
        end = len(args) - 1
        assert end >= 0
        if w_iseq.r2k:
            # ruby2_keywords: the folded hash carries the forwarding flag.
            args[end] = boot.kw_hash_dup(args[end])
        kw_hash = args[end]
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
        # The caller's frame holds these while the shim copies them.
        ary = rubycall.ary_new(values)
        # The callee is not on the mark chain yet; only this hold roots it.
        gcroots.hold(ary)
        held_ary = ary
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

    if held_ary != 0:
        gcroots.release(held_ary)
    if held_flagged != 0:
        gcroots.release(held_flagged)
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
    """args_setup_kw_parameters: match by name, unfilled marked in kwbits."""
    table = w_iseq.kw_table
    required = w_iseq.kw_required
    start = w_iseq.kw_start
    nkw = len(kw_names)
    taken = [False] * nkw
    missing = []
    # Counts **splat keys taken, so leftovers need no walk of the Hash.
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
    """The send an opt_* falls through to on Qundef (CALL_SIMPLE_METHOD)."""
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
        # The same natives invoke gives a named send; opt_* falls through here.
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
                    kw_names=NO_KEYWORDS, w_block=None):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    return _super_to_cruby_args(frame, klass, owner, mid, recv_at, args,
                                kw_splat, kw_names, w_block)


@unroll_safe
def _super_to_cruby_args(frame, klass, owner, mid, recv_at, args, kw_splat,
                         kw_names=NO_KEYWORDS, w_block=None):
    """super onto a CRuby-owned method: the one after owner on klass's chain."""
    recv = frame.stack[recv_at]
    if mid == INITIALIZE and len(args) == 0 \
            and owner == value.core_class(value.C_BASIC_OBJECT) \
            and helpers.basic_initialize_pristine():
        _drop(frame, recv_at)
        return value.Q_NIL
    if len(kw_names) > 0:
        args = _kw_to_positional(args, kw_names)
    _drop(frame, recv_at)
    # blk: the frame's own for a bare super, the written one otherwise.
    ret = rubycall.call_super(klass, owner, recv, mid, args,
                              kw_splat or len(kw_names) > 0,
                              _to_proc(w_block))
    if ret == value.Q_UNDEF:
        raise UnsupportedOperation(
            "super from '%s' reaches a method its owner does not define"
            % symbols.name_of(mid))
    _check_block_error()
    return ret


METHOD_MISSING = symbols.intern('method_missing')
RUBY2_KEYWORDS = symbols.intern('ruby2_keywords')


def _ruby2_keywords(frame, recv, recv_at):
    """Module#ruby2_keywords on a registry method: mark its ISeq."""
    mid = _name_mid(frame.stack[recv_at + 1])
    if mid == rubycall.NO_MID:
        return value.Q_UNDEF
    entry = dispatch.lookup_owned(recv, mid)
    if entry is None or entry.kind != dispatch.KIND_ISEQ:
        # A CRuby-owned method: its own Module#ruby2_keywords handles it.
        return value.Q_UNDEF
    w = entry.w_iseq
    # CRuby only marks a *rest method without keyword parameters; else warns.
    if w.rest_start < 0 or len(w.kw_table) > 0 or w.kwrest >= 0:
        return value.Q_UNDEF
    w.r2k = True
    _drop(frame, recv_at)
    return value.Q_NIL


@unroll_safe
def _super_missing_args(frame, mid, recv_at, args, kw_splat, kw_names,
                        w_block):
    """A super with no superclass method reaches method_missing (vm_eval.c)."""
    recv = frame.stack[recv_at]
    if len(kw_names) > 0:
        args = _kw_to_positional(args, kw_names)
    full = [rubycall.sym_value(mid)]
    i = 0
    while i < len(args):
        full.append(args[i])
        i += 1
    _drop(frame, recv_at)
    kw = kw_splat or len(kw_names) > 0
    proc_v = _to_proc(w_block)
    if proc_v != value.Q_NIL:
        return rubycall.call_with_proc(recv, METHOD_MISSING, full, proc_v, kw)
    if kw:
        return rubycall.call_kw(recv, METHOD_MISSING, full)
    return rubycall.call(recv, METHOD_MISSING, full)


@unroll_safe
def invoke_super(frame, w_ci, w_block=None, has_block=False):
    """A send's lookup, resumed above the running method's owner."""
    entry = frame.entry
    if entry is None:
        raise UnsupportedOperation(
            'super outside a method body is not supported')
    if w_ci.blockarg:
        # Read before pop, so frame marks it across the alloc (vm_args.c:1119).
        top = frame.sp - 1
        if top < 0:
            raise UnsupportedOperation(
                "super passes a &block the stack does not hold")
        w_block = _block_from_value(frame.block, frame.stack[top])
        frame.pop()
        # super(&nil) suppresses forwarding; only a bare super inherits.
        has_block = True
    blk = w_block if has_block else frame.block
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
    # CRuby is asked: the chain above owner may hold iclasses we lack.
    owner = dispatch.super_owner(klass, entry.owner, entry.mid)
    target = None
    if owner != value.Q_NIL:
        target = dispatch.lookup_owned(owner, entry.mid)
    if target is None and owner == value.Q_NIL:
        # vm_call_method_missing: a missing super falls back to it.
        kw_splat = w_ci.kw_splat
        if w_ci.splat:
            trailing = 1 if kw_splat else len(w_ci.kw_names)
            args = _splat_args(frame, recv_at + 1, argc - trailing, trailing)
            kw_splat = _splat_kw(args, kw_splat, trailing)
        else:
            args = []
            i = 0
            while i < argc:
                args.append(frame.stack[recv_at + 1 + i])
                i += 1
        return _super_missing_args(frame, entry.mid, recv_at, args,
                                   kw_splat, w_ci.kw_names, blk)
    if w_ci.splat:
        trailing = 1 if w_ci.kw_splat else len(w_ci.kw_names)
        args = _splat_args(frame, recv_at + 1, argc - trailing, trailing)
        kw_splat = _splat_kw(args, w_ci.kw_splat, trailing)
        if target is None:
            return _super_to_cruby_args(frame, klass, entry.owner, entry.mid,
                                        recv_at, args, kw_splat,
                                        w_ci.kw_names, blk)
        if target.kind != dispatch.KIND_ISEQ:
            return _attr_send_args(frame, target, recv, recv_at, args, blk)
        return _enter_args(frame, target, recv, recv_at, args, entry.mid,
                           blk, w_ci.kw_names, kw_splat)
    if target is None:
        return _super_to_cruby(frame, klass, entry.owner, entry.mid, recv_at,
                               argc, w_ci.kw_splat, w_ci.kw_names, blk)
    if target.kind != dispatch.KIND_ISEQ:
        return _attr_send(frame, target, recv, recv_at, argc, blk)
    return _enter(frame, target, recv, recv_at, argc,
                  entry.mid, blk, w_ci.kw_names, w_ci.kw_splat)


# alias/undef compile to a send of one of these (vm.c); registry must see.
CORE_ALIAS = symbols.intern('core#set_method_alias')
CORE_UNDEF = symbols.intern('core#undef_method')
CORE_GVAR_ALIAS = symbols.intern('core#set_variable_alias')
# Literal keywords beside a **, and bare super forwarding (vm.c:4261).
HASH_MERGE_PTR = symbols.intern('core#hash_merge_ptr')
HASH_MERGE_KWD = symbols.intern('core#hash_merge_kwd')


MODULE_FUNCTION = symbols.intern('module_function')
PRIVATE_CLASS_METHOD = symbols.intern('private_class_method')
PRIVATE = symbols.intern('private')
PUBLIC = symbols.intern('public')
REMOVE_METHOD = symbols.intern('remove_method')
UNDEF_METHOD = symbols.intern('undef_method')
ALIAS_METHOD = symbols.intern('alias_method')
INSTANCE_EVAL = symbols.intern('instance_eval')
INSTANCE_EXEC = symbols.intern('instance_exec')
CLASS_EVAL = symbols.intern('class_eval')
MODULE_EVAL = symbols.intern('module_eval')
CORE_LAMBDA = symbols.intern('lambda')
KERNEL_PROC = symbols.intern('proc')


@dont_look_inside
def _singleton_of(recv):
    """The singleton class instance_eval pushes as cref; 0 when it has none."""
    if value.is_immediate(recv):
        return 0
    return boot.singleton_class(recv)


@unroll_safe
def _instance_eval(frame, mid, recv, recv_at, argc, w_block):
    """instance_eval/exec: self rebound here; CRuby keeps the written self."""
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
        # Over the block's own chain (yield_under), never the caller's.
        cref = _push_cref(_cref_of(w_block.frame), sing, True)
    _drop(frame, recv_at)
    return call_block(w_block, args, NO_KEYWORDS, False, recv, cref)


@unroll_safe
def _module_eval_block(frame, recv, recv_at, w_block):
    """class_eval/module_eval block: CRuby would keep the written cref."""
    args = [recv]
    # Over the block's own chain (yield_under), never the caller's.
    cref = _push_cref(_cref_of(w_block.frame), recv, True)
    _drop(frame, recv_at)
    return call_block(w_block, args, NO_KEYWORDS, False, recv, cref)


def _in_body_of(frame, recv):
    node = frame.cref
    return node is not None and node.klass == recv


@unroll_safe
def _module_function(frame, recv, recv_at, argc):
    """rb_mod_modfunc: bare form makes every later def private + singleton."""
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


@unroll_safe
def _visibility_pragma(frame, mid, recv, recv_at):
    """Bare private/public: flips the default for every def that follows."""
    frame.private_pragma = (mid == PRIVATE)
    _drop(frame, recv_at)
    return recv


@unroll_safe
def _visibility_names(frame, mid, recv, recv_at, argc):
    """private :name; looked up first: CRuby's call adds a private override."""
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    entries = _lookup_all(recv, args)
    # CRuby first, so a name it rejects raises before the registry is touched.
    ret = rubycall.call(recv, mid, args)
    _mark_visibility(recv, args, entries, mid == PRIVATE)
    return ret


def _lookup_all(klass, args):
    entries = []
    i = 0
    while i < len(args):
        entries.append(dispatch.lookup(klass, symbols.intern(_attr_name(args[i]))))
        i += 1
    return entries


@dont_look_inside
def _mark_visibility(klass, args, entries, private):
    i = 0
    while i < len(args):
        entry = entries[i]
        if entry is not None and entry.kind != dispatch.KIND_UNDEF:
            name_mid = symbols.intern(_attr_name(args[i]))
            if entry.kind == dispatch.KIND_ISEQ:
                dispatch.define(klass, name_mid, entry.w_iseq, private,
                                entry.cref, entry.lexical)
            elif entry.kind == dispatch.KIND_BMETHOD:
                dispatch.define_bmethod(klass, name_mid, entry.w_block,
                                        private)
            else:
                dispatch.define_attr(klass, name_mid, entry.ivar,
                                     entry.kind, private)
        i += 1


@unroll_safe
def _remove_or_undef(frame, mid, recv, recv_at, argc):
    """remove_method/undef_method: remove exposes an ancestor's, undef not."""
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    ret = rubycall.call(recv, mid, args)
    for v in args:
        name_mid = symbols.intern(_attr_name(v))
        if mid == UNDEF_METHOD:
            dispatch.undef_method(recv, name_mid)
        else:
            dispatch.undefine(recv, name_mid)
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
        # An RPyYARV method: define installs CRuby's resolving trampoline.
        dispatch.define(cbase, name, entry.w_iseq, entry.private,
                        entry.cref, entry.lexical, entry.mid, entry.owner)
        _drop(frame, recv_at)
        return value.Q_NIL
    if entry is not None:
        # An attr entry: without this the new name lives only in the registry.
        dispatch.define_attr(cbase, name, entry.ivar, entry.kind)
    args = [cbase, frame.stack[recv_at + 2], frame.stack[recv_at + 3]]
    _drop(frame, recv_at)
    ret = rubycall.call(recv, mid, args)
    helpers.refresh()
    return ret


def _alias_method(frame, recv, recv_at):
    """alias_method: an ISEQ alias stays here, not following the old name."""
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
                                entry.cref, entry.lexical,
                                entry.mid, entry.owner)
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
    """Blocks C refers to by integer handle only: RPython's GC moves objects."""
    def __init__(self):
        self.table = []         # handle -> W_Block, None for a free slot
        # handle -> the self it was handed over under, for instance_eval yields.
        self.selves = []
        self.free = []          # handles whose GC owner died
        self.by_proc = {}       # a materialised Proc -> the block behind it
        self.error = None       # an RPython error the callback could not raise
        self.exc = None         # likewise, a Ruby exception
        self.jump = None        # likewise, a break or a non-local return


blocks = _Blocks()


def _alloc_handle(w_block):
    # Slots come back only when their GC owner died, so stored blocks live.
    while True:
        h = boot.pop_dead_handle()
        if h < 0:
            break
        _release_handle(h)
    # The sentinel, not the live receiver: a real rebind must never collide.
    here = boot.block_sentinel()
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
    # Quasi-immutable: the compare folds away; prebuilt, so not plain.
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


class _FiberKill(object):
    """RUBY_FATAL_FIBER_KILLED (internal/thread.h), asked of the shim once."""
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


fiber_kill = _FiberKill()


# rb_block_param_proxy's stand-in (insns.def:144): a Symbol, unmarked.
proxy = _Proxy()


class _Encodings(object):
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


encodings = _Encodings()


class _RegexpClass(object):
    """Regexp itself, cached to tell Regexp.last_match from a method call."""
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


regexp_class = _RegexpClass()

ENC_FIND = symbols.intern('find')
# Encoding.find is pure and Encodings immortal: one call per name.
enc_cache = {}

# CGI is absent at install(); const_at's version-keyed cache is memo enough.
CGI_CONST = symbols.intern('CGI')

SPACESHIP_CI = W_CallInfo(helpers.SPACESHIP, 1)


@unroll_safe
def _comparable_op(frame, mid, recv_at):
    """Comparable#< and friends: <=> natively, not out through compar.c."""
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
    """Q_UNDEF keeps the block's own self; else the self CRuby yielded under."""
    v = boot.as_signed(cruby_self)
    if v == blocks.selves[handle]:
        return value.Q_UNDEF
    return v


def block_callback(handle, argc, argv, cruby_self):
    """Called from C; no RPython exception may escape into libruby."""
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
        # CRuby owns the frame, so the block keeps its written cref.
        return boot.as_value(call_block(w_block, args, NO_KEYWORDS, False,
                                        _sub_self(handle, cruby_self)))
    except RubyException, e:
        # A kill goes back to CRuby as the fatal it was; ensures have run.
        boot.rethrow_if_fiber_kill(e.value)
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
        # Returning normally would let CRuby re-call on an exhausted stack.
        check_stack_overflow()
        blocks.error = UnsupportedOperation(STACK_TOO_DEEP)
        return _park_unwind()
    finally:
        if foreign:
            _leave_foreign_stack()


STACK_TOO_DEEP = 'the call is nested too deeply for RPyYARV\'s stack'


@dont_look_inside
def _park_unwind():
    """An RPython exception cannot cross libruby: the shim raises for it."""
    boot.set_block_unwind()
    return boot.as_value(value.Q_NIL)


TRAMP_OK = 0
TRAMP_RAISE = 1
TRAMP_UNSUPPORTED = 2
TRAMP_UNWIND = 3


def trampoline_callback(self_v, rid, owner_v, def_v, argc, argv, blockv, kw,
                        statusp, errp):
    """Called from C; failures leave via statusp/errp, never into libruby."""
    boot.store_int(statusp, TRAMP_OK)
    boot.store_value(errp, value.Q_NIL)
    recv = boot.as_signed(self_v)
    # The def CRuby dispatched: exact across alias/define_method copies.
    entry = dispatch.lookup_from_def(boot.as_signed(def_v))
    mid = rubycall.NO_MID
    if entry is not None:
        mid = rubycall.mid_of_rid(boot.as_signed(rid))
        if mid == rubycall.NO_MID:
            mid = entry.mid
        elif mid != entry.mid:
            # A recycled def address: distrust the map, resolve by owner.
            entry = None
    if entry is None:
        # From the owner CRuby chose: super/bind_call name an ancestor, and
        # re-deriving from self's class would loop back to the most derived.
        owner = boot.as_signed(owner_v)
        if owner == value.Q_NIL or owner == 0:
            owner = value.class_of(recv)
        mid, entry = dispatch.lookup_from_trampoline(boot.as_signed(rid),
                                                     owner)
        if entry is None and owner != value.class_of(recv):
            # Aliases and the like keep the old dynamic resolution as a net.
            mid, entry = dispatch.lookup_from_trampoline(boot.as_signed(rid),
                                                         value.class_of(recv))
    # argv lives on CRuby's VM stack for the call, so it needs no root.
    w_block = None
    proc_v = boot.as_signed(blockv)
    if proc_v != value.Q_NIL:
        w_block = block_mod.from_proc(proc_v)
    foreign = _enter_foreign_stack()
    try:
        return boot.as_value(_from_cruby(recv, mid, entry, argv,
                                         boot.as_int(argc), w_block,
                                         boot.as_int(kw) != 0))
    except RubyException, e:
        boot.rethrow_if_fiber_kill(e.value)
        boot.store_int(statusp, TRAMP_RAISE)
        boot.store_value(errp, e.value)
    except block_mod.BlockJump, e:
        # Aimed past this call: the shim raises so libruby unwinds its frames.
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
    """A Fiber's stack is unmeasured, so the depth check is off here."""
    # ponytail: off, not re-based: runaway recursion segfaults; needs rstack.
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


def _from_cruby(recv, mid, entry, argv, argc, w_block, kw_splat=False):
    """The trampoline's send half; argv/argc are CRuby's raw buffer, unread."""
    if mid == rubycall.NO_MID:
        raise UnsupportedOperation(
            'CRuby dispatched a method name RPyYARV never interned')
    if entry is None:
        raise UnsupportedOperation(
            "CRuby dispatched '%s' to RPyYARV, which no longer defines it"
            % symbols.name_of(mid))
    if entry.kind != dispatch.KIND_ISEQ:
        return _attr_from_cruby(entry, recv, boot.read_values(argv, argc),
                                w_block)
    callee_iseq = entry.w_iseq
    callee = Frame(callee_iseq, recv, None, entry)
    callee.block = w_block
    pc = 0
    if callee_iseq.simple_params and not kw_splat:
        if argc != callee_iseq.nparams:
            _arity_error(argc, callee_iseq.nparams, callee_iseq.nparams)
        # Simple params: argv's slots land straight in the callee's locals.
        i = 0
        while i < argc:
            callee.local_set(i, boot.read_value_at(argv, i))
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        pc = setup_params(callee_iseq, callee, boot.read_values(argv, argc),
                          False, NO_KEYWORDS, kw_splat)
    debug.count_native()
    return execute(callee_iseq, callee, pc)


def _attr_from_cruby(entry, recv, args, w_block=None):
    """_from_cruby's accessor case; CRuby's argv is already a marked buffer."""
    if entry.kind == dispatch.KIND_BMETHOD:
        if w_block is not None:
            return _call_with_block(recv, entry.mid, args, w_block)
        debug.count_native()
        return _run_bmethod(entry.w_block, recv, args)
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
    if w_block.kind == block_mod.KIND_PROC:
        # Already a Proc: handed over as itself, it keeps module_eval's cref.
        return rubycall.call_with_proc(recv, mid, args, w_block.proc_value, kw)
    handle = _alloc_handle(w_block)
    # No release: the handle's owner dies with the ifunc, freeing the slot.
    try:
        ret = rubycall.call_with_block(recv, mid, args, handle, kw)
    except RubyException:
        # Whatever the block parked is the reason, and takes precedence.
        _check_block_error()
        raise
    _check_block_error()
    return ret


def _check_block_error():
    """Raises what a callback could not raise through libruby's frames."""
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
    """A real Proc for an escaping block (vm_insnhelper.c:543), memoised."""
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
    """The proxy runs the block itself for these; anything else needs a Proc."""
    return mid == CALL or mid == YIELD or mid == AREF or mid == EQQ_


ARITY = symbols.intern('arity')
LAMBDA_P = symbols.intern('lambda?')


def _iseq_arity(w_iseq):
    """rb_proc_arity (proc.c:1120): min when fixed, -(min+1) otherwise."""
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
    """The block a &arg site passes on (vm_args.c:1116); takes no frame."""
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
    """A send onto a block RPyYARV holds: the proxy (compile.c:9564) or Proc."""
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
        # The Proc wraps a C yielder, so these come from the ISeq it stands for.
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
    """Run a block's ISeq in a frame chaining to the defining one's locals."""
    keyed = len(kw_names) > 0 or kw_splat
    if w_block.kind != block_mod.KIND_ISEQ:
        if keyed:
            return _call_foreign_block_kw(w_block, args, kw_names, kw_splat)
        return _call_foreign_block(w_block, args)
    # Promoted here: the frame's arrays then take constant sizes.
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
    """arg_setup_method: exact arity, no autosplat (vm_insnhelper.c:1832)."""
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
        # A later return aimed here is the orphaned LocalJumpError.
        callee.dead = True


@unroll_safe
def _run_bmethod(w_block, recv, args, kw_names=NO_KEYWORDS, kw_splat=False):
    """entry.w_block: method-style arity; return/break leave the method."""
    b_iseq = promote(w_block.w_iseq)
    outer = w_block.frame
    callee = Frame(b_iseq, recv, outer.cref, outer.entry)
    callee.defining_frame = outer
    callee.own_block = w_block
    return _run_lambda(w_block, b_iseq, callee, args, kw_names, kw_splat)


@dont_look_inside
def _call_foreign_block_kw(w_block, args, kw_names, kw_splat):
    """Keywords as the one trailing Hash RB_PASS_KEYWORDS names."""
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
    """A foreign block: a CRuby Proc, or &:sym (vm_insnhelper.c:552)."""
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
    """TODO: CRuby asks to_ary (vm_args.c:863); this takes a real Array."""
    v = args[0]
    if value.is_immediate(v):
        return args
    if value.is_plain_array(v):
        # Read in place: a call per element showed up in the profile.
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
    """The frame `level` up the chain; its locals are heap (shares_locals)."""
    f = frame
    i = 0
    while i < level:
        f = f.defining_frame
        if f is None:
            raise UnsupportedOperation(
                'a local at level %d has no enclosing scope in %s (%s)'
                % (level, frame.w_iseq.name, frame.w_iseq.path))
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
    """A throw in flight; _rethrow turns it back into an exception."""
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


# A longer chain is corrupt; the walk must terminate for the tracer.
MAX_SCOPES = 256


def _return_target(frame):
    """Nearest lambda frame, else the outermost (vm_insnhelper.c:1834)."""
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
    """return from a block; a dead target raises (vm_insnhelper.c:1926)."""
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


def _is_fiber_kill(throw):
    """Fiber#kill travels as a raise for ensures, but no rescue may take it."""
    return throw.kind == PENDING_RAISE and throw.value == fiber_kill.value \
        and fiber_kill.value != 0


def _catch_for(iseq, epc, kind, fatal=False):
    """First catch entry covering epc (vm.c:2911); break/next take ensure."""
    catches = iseq.catches
    i = 0
    while i < len(catches):
        entry = catches[i]
        if entry.start < epc and epc <= entry.end:
            if entry.kind == CATCH_ENSURE or \
                    (entry.kind == CATCH_RESCUE and kind == PENDING_RAISE
                     and not fatal) or \
                    (entry.kind == CATCH_RETRY and kind == PENDING_RETRY):
                return entry
        i += 1
    return None


def _run_catch(frame, entry, throw):
    """A catch ISeq's frame chains to the raiser's locals (vm.c:3014)."""
    w_iseq = entry.w_iseq
    callee = Frame(w_iseq, frame.self_val, frame.cref, frame.entry)
    callee.defining_frame = frame
    callee.block = frame.block
    callee.own_block = frame.own_block
    if w_iseq.nlocals > 0:
        # Local 0 is `$!`; for a break or a next nothing reads it.
        callee.local_set(0, throw.value if throw.kind == PENDING_RAISE
                         and not _is_fiber_kill(throw) else value.Q_NIL)
    callee.pending_kind = throw.kind
    callee.pending_value = throw.value
    callee.pending_block = throw.w_block
    callee.pending_frame = throw.target
    return _run_with_errinfo(w_iseq, callee, callee.local_get(0)
                             if w_iseq.nlocals > 0 else value.Q_NIL)


def _run_with_errinfo(w_iseq, callee, errinfo):
    """$! reads ec->errinfo: RPyYARV pushes no CRuby rescue frame."""
    prev = rubycall.swap_errinfo(errinfo)
    try:
        return execute(w_iseq, callee)
    finally:
        rubycall.swap_errinfo(prev)


def _unwind(iseq, frame, throw, epc):
    """Run catch entries covering epc; answers the resume pc, or re-raises."""
    while True:
        entry = _catch_for(iseq, epc, throw.kind,
                           _is_fiber_kill(throw))
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
    """RPYYARV_JITPARAM tunes the JIT as pypy's --jit does, no translation."""
    spec = os.environ.get('RPYYARV_JITPARAM')
    # function_threshold=100: Ruby methods go hot before a backedge does.
    # Eager bridges: branchy code (rubykon MCTS) needs them anyway.
    # No retrace_limit/max_retrace_guards: they segfault force_op_from_preamble.
    set_user_param(jitdriver, spec if spec else
                   'function_threshold=100,trace_eagerness=50')


def install():
    configure_reselection()
    configure_jitparams()
    boot.rb_patch_method_equality()
    boot.install_block_callback(block_callback)
    boot.install_trampoline_callback(trampoline_callback)
    gcroots.register_blocks(blocks)
    # A Symbol, so it is an immediate no mark hook has to reach.
    proxy.value = boot.sym_new(PROXY_NAME)
    fiber_kill.value = boot.fiber_killed_value()
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
    send_owners.array_each_with_index = dispatch.owner_of(
        value.core_class(value.C_ARRAY), EACH_WITH_INDEX)
    send_owners.class_allocate = dispatch.owner_of(
        value.core_class(value.C_CLASS), ALLOCATE)
    send_owners.string_force_encoding = dispatch.owner_of(
        value.core_class(value.C_STRING), FORCE_ENCODING)
    send_owners.string_unpack1 = dispatch.owner_of(
        value.core_class(value.C_STRING), UNPACK1)
    send_owners.array_pack = dispatch.owner_of(
        value.core_class(value.C_ARRAY), helpers.PACK)
    send_owners.comparable = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Comparable'))
    encodings.value = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Encoding'))
    regexp_class.value = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Regexp'))


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
    """rb_ary_cat of the n topmost onto the Array under them, left on stack."""
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
    # Copied but not popped: the frame marks them until the shim has them.
    values = [0] * n
    i = 0
    while i < n:
        values[i] = frame.stack[at + i]
        i += 1
    v = rubycall.ary_new(values)
    _drop(frame, at)
    return v


# vm_opt_newarray_send_type (vm_core.h), indexed by method-1.
NEWARRAY_SEND_MID = [helpers.MAX, helpers.MIN, helpers.HASH, helpers.PACK,
                     helpers.PACK, helpers.INCLUDE_P]


@unroll_safe
def _newarray_send(frame, n, meth):
    """vm_opt_newarray_send's fallback: build the array, send the method."""
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
        # Before the keyword Hash exists: the fused instruction allocates none.
        if send_owners.array_pack != 0 \
                and dispatch.owner_of(value.class_of(v_ary), helpers.PACK) \
                == send_owners.array_pack:
            v = boot.pack_double_into(v_ary, arg, buffer)
            if v != value.Q_UNDEF:
                debug.count_native()
                return v
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
    """n/2 pairs, left in the marked frame until rb_hash_aset copied them."""
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
    """vm_expandarray: flag 1 pushes the rest, flag 2 fills from the end."""
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
    # Quasi-immutable: a prebuilt plain field would fold to its pre-boot 0.
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


vm_core = _VMCore()


@dont_look_inside
def _vm_core():
    """RubyVM::FrozenCore, receiver of core# (vm_insnhelper.c:5668)."""
    if vm_core.value == 0:
        v = boot.vm_core()
        boot.gc_register(v)
        vm_core.value = v
    return vm_core.value


def _const_path(frame, iseq, idx):
    """A per-site memo of _const_walk; the global cache is the fallback."""
    # Keyed on the innermost class: _push_cref interns one node per pair.
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
    """vm_get_ev_const, nil cbase: lexical tables, then ancestors and Object."""
    node = cref
    # The outermost entry is toplevel Object; only the walk below covers it.
    while node.outer is not None:
        if not node.by_eval:
            v = dispatch.const_at(node.klass, mid)
            if v != value.Q_UNDEF:
                return v
        node = node.outer
    return dispatch.const_get(_cref_klass(cref), mid)


def _cref_klass(cref):
    # const_base, not klass: an instance_eval scope names no constants.
    if cref.const_base == 0:
        return value.core_class(value.C_OBJECT)
    return cref.const_base


def _run_once(frame, iseq, idx):
    """A `once` body, in a frame chained to this one; result cached."""
    body = iseq.iseqs[idx]
    callee = Frame(body, frame.self_val, _cref_of(frame), frame.entry)
    callee.defining_frame = frame
    v = execute(body, callee)
    iseq.once_cache[idx] = v
    return v


@dont_look_inside
def _cvar_base(cref):
    """vm_get_cvar_base: innermost lexical scope that is a real class."""
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


def _cbase(frame):
    """vm_get_cbase: innermost cref klass, an eval-pushed one included."""
    node = frame.cref
    if node is not None and node.klass != 0:
        return node.klass
    return _const_base(frame)


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
    """A fresh instance, or 0; only RPyYARV's classes kept Class#new."""
    # Promoted: both tests fold, leaving only the allocation in the trace.
    klass = promote(klass)
    if not dispatch.is_known_class(klass):
        return 0
    if helpers.ary_new_pristine(klass):
        # The miss branch's `send new` is where _array_new runs.
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
        # TODO: a subclass redefining #=== is ignored, as in vm_opt_*.
        return boot.obj_is_kind_of(target, pattern)
    return value.is_true(rubycall.call1(pattern, EQQ, target))


def _binop(frame, recv, arg, mid):
    """Both operands back on the marked stack before the send allocates."""
    frame.push(recv)
    frame.push(arg)
    return _opt_send(frame, mid, 1)


def _unop(frame, recv, mid):
    frame.push(recv)
    return _opt_send(frame, mid, 0)


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


# is_recursive: a portal call at an inlining limit escapes the virtualizable.
jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'], is_recursive=True,
                      get_printable_location=get_printable_location)


class _Reselection(object):
    """One deliberate reselection: the first traces come off a cold profile."""
    # Quasi-immutable, so disabling folds the counter below out of every trace.
    _immutable_fields_ = ['enabled?']

    def __init__(self):
        self.enabled = True
        self.count = 0
        self.at = RESELECT_AT


# Late enough for a warm profile, early enough to still be measured.
RESELECT_AT = 2000000

reselection = _Reselection()


def configure_reselection():
    """RPYYARV_RESELECT_AT sets the backedge count to reselect at; 0 off."""
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
            # Disabling invalidates every trace, which is the reselection.
            reselection.enabled = False


def _epc(iseq, pc):
    """Catch-table ranges are against the pc *after* the raising instruction."""
    return pc + 1 + optable.NUM_OPERANDS[iseq.code[pc]]


def execute(iseq, frame, pc=0):
    """Two shapes: the handler shape stops the JIT inlining; iseq is green."""
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
    """A frame a `return` in one of its blocks names (valid_return)."""
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
    # No loop: it would stop the tracer inlining this and abort the trace.
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
        # Only an unwinding exception reads this; the store is free in a trace.
        frame.pc = pc
        # Rebound each iteration: hoisting leaves a live non-green, non-red var.
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
            elif kind == optable.SPECIAL_OBJECT_CBASE:
                # vm_get_cbase: an eval-pushed cref counts, unlike CONST_BASE.
                frame.push(_cbase(frame))
            else:
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
                # Receiver of the initialize send; below it, that send's result.
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
        elif opcode == insns.SENDFORWARD:
            idx = code[pc]
            pc += 2
            w_ci = iseq.callinfos[idx]
            at = frame.sp - 1 - w_ci.argc
            assert at >= 0
            # The frame's own block rides along, as a bare super forwards it.
            frame.push(_splat_invoke(frame, w_ci, at, w_ci.argc, frame.block,
                                     w_ci.mid, w_ci.fcall))
        elif opcode == insns.INVOKESUPERFORWARD:
            idx = code[pc]
            pc += 2
            frame.push(invoke_super(frame, iseq.callinfos[idx]))
        elif opcode == insns.INVOKESUPER:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            if block != NO_BLOCK_ISEQ:
                w_blk = block_mod.W_Block(iseq.iseqs[block], frame,
                                          frame.block)
                frame.push(invoke_super(frame, iseq.callinfos[idx], w_blk,
                                        True))
            else:
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
            # A set bit means unfilled, so the body computes the default.
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
        elif opcode == insns.SPLATKW:
            block_v = frame.pop()
            hash_v = frame.pop()
            frame.push(value.Q_NIL if hash_v == value.Q_NIL
                       else rubycall.to_hash_type(hash_v))
            frame.push(block_v)
        elif opcode == insns.OPT_DUPARRAY_SEND:
            idx = code[pc]
            mid = code[pc + 1]
            pc += 3
            arg = frame.pop()
            frame.push(rubycall.call1(
                rubycall.ary_resurrect(iseq.consts[idx]), mid, arg))
        else:
            raise UnsupportedOperation(
                'unknown opcode %d in %s (%s) at pc %d'
                % (opcode, iseq.name, iseq.path, pc))


def run(iseq):
    debug.dump_iseq(iseq)
    ret = execute(iseq, Frame(iseq, boot.top_self()))
    debug.summary()
    return ret


def run_in_cruby():
    """The whole script handed back; its answer is the exit status."""
    return boot.run_node()
