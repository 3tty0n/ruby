"""The send path: method lookup, dispatch and native fast paths."""
from __future__ import absolute_import

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import dispatch
from rpyyarv import helpers
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import UnsupportedOperation
from rpyyarv.frame import Frame
from rpyyarv.rlib import always_inline, dont_look_inside, promote, raw_word, unroll_safe, we_are_jitted

from rpyyarv.interp.consts_ids import ABS, ALIAS_METHOD, ALLOCATE, ARITY, ATTR_ACCESSOR, ATTR_READER, ATTR_WRITER, BACKTRACE_PRIM, BINDING, BLOCK_GIVEN, BUFFER, CALLEE_UNDERSCORE, CGI_CONST, CLASS_EVAL, CORE_ALIAS, CORE_GVAR_ALIAS, CORE_LAMBDA, CORE_UNDEF, DEFINE, DEFINE_METHOD, DIR_UNDERSCORE, EACH_SLICE, EACH_WITH_INDEX, ENC_FIND, EVAL, FIRST, FORCE_ENCODING, FREEZE, GETBYTE, HASH_MERGE_KWD, HASH_MERGE_PTR, HASH_PAIRS_PRIM, INDEX, INITIALIZE, INSTANCE_EVAL, INSTANCE_EXEC, ITSELF, KERNEL_PROC, LAMBDA_P, LAST, MATCH, METHOD_UNDERSCORE, MODULE_EVAL, MODULE_FUNCTION, NEGATIVE_P, NEW, OFFSET, ORD, OWNER, PARAMETERS, PRIVATE, PRIVATE_CLASS_METHOD, PROTECTED, PUBLIC, PUBLIC_SEND, REMOVE_METHOD, REQUIRE_PRIM, REVERSE_EACH, RUBY2_KEYWORDS, SEND, SEND2, SETBYTE, SLICE, STEP, TO_A, TO_I, TO_INT, TO_SYM, UNDEF_METHOD, UNPACK1
from rpyyarv.interp.args import NO_KEYWORDS, _arity_error, _kw_to_positional, _refuse_iseq, setup_params


@always_inline
def zero_arg_native(recv, klass, mid):
    """argc 0 core methods, Q_UNDEF when none matches; &:sym shares this."""
    # Kernel#freeze is rb_obj_freeze: a C call, not a send back through it.
    if mid == FREEZE and dispatch.owner_of(klass, FREEZE) == \
            send_owners.kernel:
        return boot.obj_freeze(recv)
    # Symbol#to_sym and Array#to_a answer with the receiver itself.
    if mid == TO_SYM and klass == value.core_class(value.C_SYMBOL) \
            and dispatch.owner_of(klass, TO_SYM) == klass:
        return recv
    if mid == TO_A and value.is_plain_array(recv) \
            and dispatch.owner_of(klass, TO_A) == \
            value.core_class(value.C_ARRAY):
        return recv
    if mid == NEGATIVE_P and value.is_fixnum(recv) \
            and dispatch.owner_of(klass, NEGATIVE_P) == \
            value.core_class(value.C_INTEGER):
        return value.newbool(value.fix2int(recv) < 0)
    if mid == FIRST and value.is_plain_array(recv) \
            and dispatch.owner_of(klass, FIRST) == \
            value.core_class(value.C_ARRAY):
        if value.ary_len(recv) == 0:
            return value.Q_NIL
        return value.ary_at(recv, 0)
    if mid == LAST and value.is_plain_array(recv) \
            and dispatch.owner_of(klass, LAST) == \
            value.core_class(value.C_ARRAY):
        n = value.ary_len(recv)
        return value.Q_NIL if n == 0 else value.ary_at(recv, n - 1)
    if (mid == TO_I or mid == TO_INT) and value.is_fixnum(recv) \
            and dispatch.owner_of(klass, mid) == \
            value.core_class(value.C_INTEGER):
        return recv
    if mid == ABS and value.is_flonum(recv) \
            and dispatch.owner_of(klass, ABS) == \
            value.core_class(value.C_FLOAT):
        d = value.float_val(recv)
        if d < 0.0:
            d = -d
        if d != 0.0:
            v = value.dbl2flonum(d)
            if v != value.Q_UNDEF:
                return v
    # String#to_sym: rb_str_intern, protected (encoding table can raise).
    if mid == TO_SYM and value.is_plain_string(recv) \
            and dispatch.owner_of(klass, TO_SYM) == \
            value.core_class(value.C_STRING):
        v = boot.str_intern(recv)
        if v != value.Q_UNDEF:
            return v
    if mid == ORD and value.is_plain_string(recv) \
            and dispatch.owner_of(klass, ORD) == \
            value.core_class(value.C_STRING):
        v = boot.str_ord(recv)
        if v != value.Q_UNDEF:
            return v
    return value.Q_UNDEF

@unroll_safe
def invoke(frame, w_ci, w_block=None):
    if w_ci.blockarg:
        # Read before pop, so frame marks it across the alloc (vm_args.c:1119).
        top = frame.sp - 1
        if top < 0:
            raise UnsupportedOperation(
                "call to '%s' passes a &block the stack does not hold"
                % symbols.name_of(w_ci.mid))
        w_block = _block_from_value(frame.block, frame.slots[top])
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
    recv = frame.slots[recv_at]
    # Promoted: the class-word guard is the inline cache; lookup folds away.
    klass = promote(value.class_of(recv))
    while mid == SEND or mid == SEND2 or mid == PUBLIC_SEND:
        # public_send resolves the same way, but the callee stays public.
        public = mid == PUBLIC_SEND
        target = _send_target(frame, klass, mid, argc, recv_at)
        if target == rubycall.NO_MID:
            break
        _shift_off(frame, recv_at)
        argc -= 1
        mid = target
        fcall = not public
    if mid == w_ci.mid and not we_are_jitted():
        entry = dispatch.site_lookup(w_ci, klass, mid)
    else:
        entry = dispatch.lookup(klass, mid)
    callee_iseq = None
    if _protected_ok(frame, entry, fcall):
        fcall = True
    if entry is not None and (fcall or not (entry.private or entry.prot)):
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
    if argc == 0 and entry is None and w_block is None:
        v = zero_arg_native(recv, klass, mid)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if mid == GETBYTE and argc == 1 and \
            dispatch.owner_of(klass, GETBYTE) == send_owners.string_getbyte:
        v = boot.str_getbyte(recv, frame.slots[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if mid == SETBYTE and argc == 2 and \
            dispatch.owner_of(klass, SETBYTE) == send_owners.string_setbyte:
        v = boot.str_setbyte(recv, frame.slots[recv_at + 1],
                             frame.slots[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if mid == SLICE and argc == 2 and entry is None and \
            value.is_plain_array(recv) and \
            dispatch.owner_of(klass, SLICE) == value.core_class(value.C_ARRAY):
        beg = frame.slots[recv_at + 1]
        length = frame.slots[recv_at + 2]
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
        v = boot.str_force_encoding_fast(recv, frame.slots[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 and w_block is None and mid == UNPACK1 \
            and send_owners.string_unpack1 != 0 \
            and dispatch.owner_of(klass, UNPACK1) == \
            send_owners.string_unpack1:
        v = boot.unpack1_double(recv, frame.slots[recv_at + 1],
                                value.int2fix(0))
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc <= 1:
        # A send an opt_* instruction would have caught if YARV had one for it.
        if argc == 1:
            v = _native_binop(recv, frame.slots[recv_at + 1], mid)
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
        v = helpers.last_match1(frame.slots[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 and mid == helpers.ESCAPE_HTML_MID \
            and recv == dispatch.const_at(value.core_class(value.C_OBJECT),
                                          CGI_CONST):
        # const_at is Qundef until cgi/escape defines CGI: an elidable miss.
        v = helpers.cgi_escape_html(frame.slots[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and mid == helpers.BYTESLICE:
        v = helpers.str_byteslice(recv, frame.slots[recv_at + 1],
                                  frame.slots[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and mid == helpers.TR:
        v = helpers.str_tr(recv, frame.slots[recv_at + 1],
                           frame.slots[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and w_block is None \
            and (mid == helpers.GSUB or mid == helpers.GSUB_BANG
                 or mid == helpers.SUB or mid == helpers.SUB_BANG):
        v = helpers.str_gsub2(recv, frame.slots[recv_at + 1],
                              frame.slots[recv_at + 2], mid)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and fcall and w_block is None and argc >= 2 \
            and argc - 1 <= boot.MAX_ARGC \
            and (mid == helpers.FORMAT_MID or mid == helpers.SPRINTF_MID):
        fmt = frame.slots[recv_at + 1]
        args = []
        i = 0
        while i < argc - 1:
            args.append(frame.slots[recv_at + 2 + i])
            i += 1
        v = helpers.kernel_format(recv, fmt, args, mid)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 1 and w_block is None \
            and mid == helpers.MATCH_MID:
        v = helpers.str_match(recv, frame.slots[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 2 and mid == helpers.ASET:
        v = helpers.hash_aset(recv, frame.slots[recv_at + 1],
                              frame.slots[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and argc == 3 and mid == helpers.ASET:
        v = helpers.ary_splice_set(recv, frame.slots[recv_at + 1],
                                   frame.slots[recv_at + 2],
                                   frame.slots[recv_at + 3])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and mid == BINDING and fcall and argc == 0 \
            and w_block is None \
            and dispatch.owner_of(klass, BINDING) == send_owners.binding:
        v = _binding_rpy(frame)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and mid == EVAL and fcall \
            and (argc == 1 or (argc == 3 \
                              and frame.slots[recv_at + 2] == value.Q_NIL)):
        v = _eval_rpy(frame, klass, recv, frame.slots[recv_at + 1])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    if entry is None and (mid == CLASS_EVAL or mid == MODULE_EVAL) and \
            w_block is None and argc >= 1 and argc <= 3 and \
            _eval_receiver(recv):
        v = _module_eval_rpy(frame, recv, frame.slots[recv_at + 1],
                             frame.slots[recv_at + 2] if argc >= 2
                             else value.Q_NIL,
                             frame.slots[recv_at + 3] if argc >= 3 else 0)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    # rb_mod_initialize module_execs the block, so a def lands on the class.
    if mid == NEW and w_block is not None and entry is None and argc <= 1 \
            and w_block.kind == block_mod.KIND_ISEQ \
            and (recv == value.core_class(value.C_CLASS)
                 or (argc == 0
                     and recv == value.core_class(value.C_MODULE))) \
            and dispatch.owner_of(klass, NEW) == \
            value.core_class(value.C_CLASS):
        return _class_new_block(frame, recv, recv_at, argc, w_block)
    # rb_struct_s_def module_execs its block the same way, on the new Struct.
    if mid == NEW and w_block is not None and entry is None \
            and w_block.kind == block_mod.KIND_ISEQ \
            and send_owners.struct_class != 0 \
            and recv == send_owners.struct_class:
        return _class_new_block(frame, recv, recv_at, argc, w_block)
    # Data.define does the same for the Data class it makes (struct.c).
    if mid == DEFINE and w_block is not None and entry is None \
            and w_block.kind == block_mod.KIND_ISEQ \
            and send_owners.data_class != 0 \
            and recv == send_owners.data_class:
        return _class_new_block(frame, recv, recv_at, argc, w_block, DEFINE)
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
            and _attr_name(frame.slots[recv_at + 1]) != '':
        return _define_bmethod(frame, mid, recv, recv_at, w_block,
                               frame.private_pragma)
    if mid == DEFINE_METHOD and argc == 1 and frame.module_func \
            and _attr_name(frame.slots[recv_at + 1]) != '':
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
        v = rubycall.hooks.require.from_cruby(frame.slots[recv_at + 1])
        _drop(frame, recv_at)
        return v
    if mid == HASH_PAIRS_PRIM and fcall and argc == 1 \
            and boot.is_hash(frame.slots[recv_at + 1]):
        v = boot.hash_pairs(frame.slots[recv_at + 1])
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
            size = frame.slots[recv_at + 1] if argc >= 1 else value.Q_NIL
            fill = frame.slots[recv_at + 2] if argc == 2 else value.Q_NIL
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
        size = frame.slots[recv_at + 1]
        if value.is_fixnum(size) and value.fix2int(size) > 0:
            _drop(frame, recv_at)
            try:
                return _array_each_slice(recv, value.fix2int(size), w_block)
            except block_mod.BlockBreak, e:
                if e.w_block is not w_block:
                    raise
                return e.value
    if mid == PARAMETERS and argc == 0 and entry is None and w_block is None:
        v = _parameters_of(recv)
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    # Struct#initialize is a C method, so a send would leave for CRuby.
    # Only reached for a simple call: keywords route through _kw_invoke, and
    # a positional Struct takes those as members (struct.c:315).
    if mid == NEW and entry is None and w_block is None \
            and send_owners.struct_class != 0 \
            and dispatch.owner_of(promote(recv), INITIALIZE) == \
            send_owners.struct_class:
        v = _struct_new(frame, recv, recv_at, argc)
        if v != value.Q_UNDEF:
            debug.count_native()
            return v
    if w_block is not None and mid == STEP and entry is None \
            and (argc == 1 or argc == 2) and value.is_fixnum(recv) \
            and send_owners.integer_step != 0 \
            and dispatch.owner_of(klass, STEP) == send_owners.integer_step:
        limit = frame.slots[recv_at + 1]
        step = frame.slots[recv_at + 2] if argc == 2 else value.int2fix(1)
        if value.is_fixnum(limit) and value.is_fixnum(step) \
                and value.fix2int(step) != 0:
            _drop(frame, recv_at)
            try:
                return _integer_step(recv, limit, step, w_block)
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
                if argc == 0 and index < value.struct_len(recv):
                    _drop(frame, recv_at)
                    return value.struct_at(recv, index)
                elif (raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE) == 0:
                    out = frame.slots[recv_at + 1]
                    boot.struct_set(recv, index, out)
                    _drop(frame, recv_at)
                    return out
    if proxy.value != 0 and recv == proxy.value:
        return _block_send(frame, mid, recv_at, argc, frame.block)
    if _is_proxy_call(mid) or mid == ARITY or mid == LAMBDA_P:
        w_own = _proc_block_of(recv)
        if w_own is not None:
            # A Proc RPyYARV made: run its block here, not out through CRuby.
            return _block_send(frame, mid, recv_at, argc, w_own)
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
    if (mid == PRIVATE or mid == PUBLIC or mid == PROTECTED) \
            and fcall and argc == 0 and _in_body_of(frame, recv):
        return _visibility_pragma(frame, mid, recv, recv_at)
    if (mid == PRIVATE or mid == PUBLIC or mid == PROTECTED) \
            and fcall and argc > 0 \
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
    # core_hash_merge: one aset per pair, so a big literal never hits MAX_ARGC.
    if vm_core.value != 0 and recv == vm_core.value and mid == HASH_MERGE_PTR \
            and argc >= 1 and (argc & 1) == 1 \
            and not value.is_immediate(frame.slots[recv_at + 1]) \
            and raw_word(frame.slots[recv_at + 1], value.KLASS_WORD) == \
            value.core_class(value.C_HASH):
        h = frame.slots[recv_at + 1]
        i = 0
        while i < argc - 1:
            rubycall.hash_aset(h, frame.slots[recv_at + 2 + i],
                               frame.slots[recv_at + 3 + i])
            i += 2
        _drop(frame, recv_at)
        debug.count_native()
        return h
    if vm_core.value != 0 and recv == vm_core.value \
            and mid != HASH_MERGE_PTR and mid != HASH_MERGE_KWD:
        if mid == CORE_GVAR_ALIAS and argc == 2:
            boot.alias_variable(frame.slots[recv_at + 1],
                                frame.slots[recv_at + 2])
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

    # Short calls skip the args list: it is two allocations per foreign send.
    if w_block is None and argc <= 3 and not debug.state.enabled:
        a0 = frame.slots[recv_at + 1] if argc > 0 else 0
        a1 = frame.slots[recv_at + 2] if argc > 1 else 0
        a2 = frame.slots[recv_at + 3] if argc > 2 else 0
        _drop(frame, recv_at)
        ret = rubycall.calln(recv, mid, a0, a1, a2, argc,
                             entry is not None and not fcall)
        _check_block_error()
        return ret
    args = []
    i = 0
    while i < argc:
        args.append(frame.slots[recv_at + 1 + i])
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


def _protected_ok(frame, entry, fcall):
    """protected: an explicit receiver is fine while the caller is kin."""
    if fcall or entry is None or not entry.prot:
        return False
    return dispatch.kind_of(promote(value.class_of(frame.self_val)),
                            entry.owner) == 1


def _is_attr_mid(mid):
    return (mid == ATTR_READER or mid == ATTR_WRITER
            or mid == ATTR_ACCESSOR)


class _MethodClasses(object):
    # Quasi-immutable: install() writes them once, before any Ruby code runs.
    _immutable_fields_ = ['method?', 'unbound?']

    def __init__(self):
        self.method = 0
        self.unbound = 0


method_classes = _MethodClasses()


class _SendOwners(object):
    # Quasi-immutable: install() writes it once, before any Ruby code runs.
    _immutable_fields_ = ['kernel?', 'basic?', 'string_getbyte?',
                          'string_setbyte?', 'array_each_slice?',
                          'array_each_with_index?', 'integer_step?', 'struct_class?',
                          'data_class?',
                          'comparable?', 'class_allocate?',
                          'string_force_encoding?', 'string_unpack1?',
                          'array_pack?']

    def __init__(self):
        self.kernel = 0
        self.basic = 0
        self.eval = 0
        self.binding = 0
        self.string_getbyte = 0
        self.string_setbyte = 0
        self.array_each_slice = 0
        self.array_each_with_index = 0
        self.integer_step = 0
        self.struct_class = 0
        self.data_class = 0
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
    return _send_target_of(klass, mid, frame.slots[recv_at + 1])


def _send_target_of(klass, mid, name):
    """vm_call_opt_send: the method a send names, or NO_MID if not pristine."""
    if mid == SEND:
        if not helpers.kernel_send_pristine():
            return rubycall.NO_MID
        owner = send_owners.kernel
    elif mid == PUBLIC_SEND:
        if not helpers.kernel_public_send_pristine():
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
        frame.slots[i] = frame.slots[i + 1]
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
    if mid == helpers.INCLUDE_P or mid == helpers.COVER_P \
            or mid == helpers.MEMBER_P or mid == helpers.EQQ:
        v = helpers.range_include(recv, arg, mid)
        if v != value.Q_UNDEF:
            return v
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
    if mid == helpers.ROTATE_BANG:
        return helpers.ary_rotate_bang(recv, arg)
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
        v = helpers.int_pow(recv, arg)
        if v != value.Q_UNDEF:
            return v
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
            args[i] = frame.slots[recv_at + 1 + i]
            i += 1
        _drop(frame, recv_at)
        # A block here must reach a yield in the body: left to CRuby's bmethod.
        if w_block is not None:
            return _call_with_block(recv, entry.mid, args, w_block)
        debug.count_native()
        return _run_bmethod(entry, recv, args)
    if entry.kind == dispatch.KIND_ATTR_READER:
        if argc != 0:
            _arity_error(argc, 0, 0)
        _drop(frame, recv_at)
        debug.count_native()
        return dispatch.ivar_get(recv, entry.ivar)
    if argc != 1:
        _arity_error(argc, 1, 1)
    # Stored before the drop: ivar_set may allocate, and the frame marks it.
    v = frame.slots[recv_at + 1]
    dispatch.ivar_set(recv, entry.ivar, v)
    _drop(frame, recv_at)
    debug.count_native()
    return v


@dont_look_inside
def _parameters_of(recv):
    """CRuby sees an RPyYARV def as a cfunc, so answer from the ISeq itself."""
    w_block = _proc_block_of(recv)
    if w_block is not None:
        if w_block.w_iseq is None:
            return value.Q_UNDEF
        return _iseq_parameters(w_block.w_iseq, not w_block.is_lambda)
    if value.is_immediate(recv):
        return value.Q_UNDEF
    klass = value.class_of(recv)
    if klass != method_classes.method and klass != method_classes.unbound:
        return value.Q_UNDEF
    owner = rubycall.call0(recv, OWNER)
    sym = rubycall.call0(recv, helpers.NAME)
    if value.is_immediate(owner) \
            or value.class_of(sym) != value.core_class(value.C_SYMBOL):
        return value.Q_UNDEF
    entry = dispatch.lookup_owned(owner, symbols.intern(boot.sym_of(sym)))
    if entry is None:
        return value.Q_UNDEF
    if entry.kind == dispatch.KIND_BMETHOD and entry.w_block is not None:
        if entry.w_block.w_iseq is None:
            return value.Q_UNDEF
        return _iseq_parameters(entry.w_block.w_iseq, False)
    if entry.kind != dispatch.KIND_ISEQ or entry.w_iseq is None:
        return value.Q_UNDEF
    return _iseq_parameters(entry.w_iseq, False)


def _struct_new(frame, recv, recv_at, argc):
    """Allocate and fill the slots; rb_struct_initialize does only that."""
    n = dispatch.struct_arity(promote(recv))
    if n < 0 or argc > n:
        return value.Q_UNDEF
    obj = boot.struct_alloc(recv)
    if obj == value.Q_UNDEF:
        return value.Q_UNDEF
    # Into the marked slot the class held: a constant still names the class.
    frame.slots[recv_at] = obj
    i = 0
    while i < argc:
        boot.struct_set(obj, i, frame.slots[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    return obj


def _new_with_block(frame, entry, klass, recv_at, argc, w_block):
    """Klass.new { }: CRuby's Class#new gives initialize a dying handle."""
    obj = dispatch.alloc(klass)
    # Into the caller's marked slot; _enter drops it after placing args.
    frame.slots[recv_at] = obj
    _enter(frame, entry, obj, recv_at, argc, INITIALIZE, w_block)
    return obj


@unroll_safe
def _kw_splat_hash(frame, at):
    """vm_caller_setup_keyword_hash: to_hash first; nil means no keywords."""
    # Restated so the codewriter sees the stack index as non-negative.
    assert at >= 0
    v = frame.slots[at]
    if v == value.Q_NIL or (not value.is_immediate(v) and _is_hash(v)):
        return
    frame.slots[at] = rubycall.to_hash_type(v)


@dont_look_inside
def _is_hash(v):
    return boot.is_hash(v)


def _makes_class(recv, mid):
    if mid == NEW:
        return send_owners.struct_class != 0 \
            and recv == send_owners.struct_class
    if mid == DEFINE:
        return send_owners.data_class != 0 and recv == send_owners.data_class
    return False


@unroll_safe
def _kw_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall):
    """A send with VM_CALL_KWARG keywords or a VM_CALL_KW_SPLAT Hash on top."""
    if w_ci.kw_splat:
        _kw_splat_hash(frame, recv_at + argc)
    if w_ci.splat:
        return _splat_invoke(frame, w_ci, recv_at, argc, w_block, mid, fcall)
    rubycall.gc_stress_point()
    recv = frame.slots[recv_at]
    klass = promote(value.class_of(recv))
    # Keywords stay topmost, so only the name below them is shifted off.
    while mid == SEND or mid == SEND2 or mid == PUBLIC_SEND:
        public = mid == PUBLIC_SEND
        target = _send_target(frame, klass, mid, argc - len(w_ci.kw_names),
                              recv_at)
        if target == rubycall.NO_MID:
            break
        _shift_off(frame, recv_at)
        argc -= 1
        mid = target
        fcall = not public
    entry = dispatch.lookup(klass, mid)
    if _protected_ok(frame, entry, fcall):
        fcall = True
    if entry is not None and (fcall or not (entry.private or entry.prot)):
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
        v = boot.unpack1_double(recv, frame.slots[recv_at + 1],
                                frame.slots[recv_at + 2])
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
        v = boot.pack_double_into(recv, frame.slots[recv_at + 1],
                                  frame.slots[recv_at + 2])
        if v != value.Q_UNDEF:
            _drop(frame, recv_at)
            debug.count_native()
            return v
    # A block RPyYARV holds runs here, keywords never crossing libruby.
    if proxy.value != 0 and recv == proxy.value:
        return _block_send(frame, mid, recv_at, argc, frame.block,
                           w_ci.kw_names, w_ci.kw_splat)
    if _is_proxy_call(mid):
        w_own = _proc_block_of(recv)
        if w_own is not None:
            return _block_send(frame, mid, recv_at, argc, w_own,
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
        args.append(frame.slots[base + i])
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
                               frame.slots[base + n + i])
            i += 1
        args.append(h)
    _drop(frame, recv_at)
    # Struct.new(..., keyword_init: true) still module_execs its block.
    if w_block is not None and entry is None and not w_ci.blockarg \
            and w_block.kind == block_mod.KIND_ISEQ \
            and _makes_class(recv, mid):
        if pass_kw:
            made = rubycall.call_kw(recv, mid, args)
        else:
            made = rubycall.call(recv, mid, args)
        return _exec_on_made(frame, made, w_block)
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
        args.append(frame.slots[j])
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
        args.append(frame.slots[j])
        i += 1
    splat_at = at + npos - 1
    assert splat_at >= 0
    ary = frame.slots[splat_at]
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
        args.append(frame.slots[j])
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
    recv = frame.slots[recv_at]
    klass = promote(value.class_of(recv))
    while mid == SEND or mid == SEND2 or mid == PUBLIC_SEND:
        public = mid == PUBLIC_SEND
        if len(args) - trailing < 1:
            break
        target = _send_target_of(klass, mid, args[0])
        if target == rubycall.NO_MID:
            break
        args = args[1:]
        mid = target
        fcall = not public
    entry = dispatch.lookup(klass, mid)
    if _protected_ok(frame, entry, fcall):
        fcall = True
    if entry is not None and (fcall or not (entry.private or entry.prot)):
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
    if _is_proxy_call(mid):
        w_proc = _proc_block_of(recv)
        if w_proc is not None:
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
        return _run_bmethod(entry, recv, args)
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
            callee.local_set(i, frame.slots[recv_at + 1 + i])
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        # Copied out: the codewriter refuses a virtualizable array passed on.
        given = [0] * argc
        i = 0
        while i < argc:
            given[i] = frame.slots[recv_at + 1 + i]
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


@unroll_safe
def _opt_send(frame, mid, argc):
    """The send an opt_* falls through to on Qundef (CALL_SIMPLE_METHOD)."""
    recv_at = frame.sp - argc - 1
    assert recv_at >= 0
    rubycall.gc_stress_point()
    recv = frame.slots[recv_at]
    klass = promote(value.class_of(recv))
    entry = dispatch.lookup(klass, mid)
    if entry is not None and not entry.private:
        if entry.kind != dispatch.KIND_ISEQ:
            return _attr_send(frame, entry, recv, recv_at, argc)
        return _enter(frame, entry, recv, recv_at, argc, mid, None)
    if entry is None and argc <= 1:
        # The same natives invoke gives a named send; opt_* falls through here.
        if argc == 1:
            v = _native_binop(recv, frame.slots[recv_at + 1], mid)
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
        args.append(frame.slots[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    return rubycall.call(recv, mid, args)


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.builtins import _iseq_parameters, _array_each_slice, _array_each_with_index, _integer_step, _array_new, _array_new_block, _backtrace, _comparable_op, _dir_of, _encoding_find, _running_method, encodings, proxy, regexp_class, vm_core
from rpyyarv.interp.supers import _ruby2_keywords
from rpyyarv.interp.defs import _class_new_block, _exec_on_made, _alias_method, _attr_name, _core_method, _define_attrs, _define_bmethod, _define_bmethod_modfunc, _in_body_of, _instance_eval, _module_eval_block, _module_function, _private_class_method, _remove_or_undef, _visibility_names, _visibility_pragma
from rpyyarv.interp.evalsrc import _binding_rpy, _eval_receiver, _eval_rpy, _module_eval_rpy
from rpyyarv.interp.blocks import _block_from_value, _block_send, _block_send_args, _is_proxy_call, _proc_block_of, _run_bmethod, _to_proc
from rpyyarv.interp.callbacks import _call_with_block, _check_block_error
from rpyyarv.interp.stackops import _drop
from rpyyarv.interp.execute import execute
