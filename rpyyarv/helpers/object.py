"""Generic-receiver Kernel/BasicObject fast paths."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.rlib import promote, raw_word
from rpyyarv.helpers.core import *
from rpyyarv.helpers.core import (_ary_op, _core_op, _cruby_owns, _dbl,
                                  _fix2, _flt2, _int_op, _owned_by_core)
from rpyyarv.helpers.array import (_ary_eq_false, ary_flatten_bang,
                                   ary_hash_freeze, ary_pop, ary_shift,
                                   ary_sub_length)
from rpyyarv.helpers.hash import hash_aref, hash_aset, hash_keys
from rpyyarv.helpers.numeric import (flt_to_i, flt_uminus, int_abs,
                                     int_bitref, int_to_s, int_uminus, to_f)
from rpyyarv.helpers.string import (_str_eq, ss_zero, str_ascii_only_p,
                                    str_bytesize, str_case, str_dup,
                                    str_length, str_to_s, str_uminus)
from rpyyarv.helpers.symbol import _sym_eq, sym_name, sym_to_s


def instance_eval_pristine(mid):
    """instance_eval/exec still CRuby's; a BasicObject def needs registry."""
    if mid == INSTANCE_EVAL:
        return _core_op(value.C_BASIC_OBJECT, B_BASIC_INSTANCE_EVAL,
                        INSTANCE_EVAL)
    return _core_op(value.C_BASIC_OBJECT, B_BASIC_INSTANCE_EXEC, INSTANCE_EXEC)


def basic_initialize_pristine():
    """BasicObject#initialize is still rb_obj_dummy_initialize: no arg, nil."""
    return _cruby_owns(B_BASIC_INITIALIZE)


def basic_initialize(klass):
    return (basic_initialize_pristine()
            and dispatch.owner_of(klass, INITIALIZE)
            == value.core_class(value.C_BASIC_OBJECT))


def identity_op(recv, mid):
    """vm_opt_equality's second half: mid still resolves to BasicObject's."""
    klass = value.class_of(recv)
    if klass == 0:
        return False
    klass = promote(klass)
    if mid == NEQ:
        # BasicObject#!= is defined in terms of #==, so both must be untouched.
        return (dispatch.owns_identity(klass, NEQ)
                and dispatch.owns_identity(klass, EQ))
    return dispatch.owns_identity(klass, mid)


def identity_send(recv, mid):
    """==, != or equal? that comes down to comparing the two words."""
    if mid != EQUAL_P and _sym_eq(recv, mid):
        return True
    return identity_op(recv, mid)


def kind_of(recv, target, mid):
    """Kernel#kind_of?/#is_a? cached per (class, module), so it folds."""
    bit = B_KERNEL_KIND_OF if mid == KIND_OF_P else B_KERNEL_IS_A
    if not _cruby_owns(bit):
        return value.Q_UNDEF
    if value.is_immediate(target):
        return value.Q_UNDEF
    klass = value.class_of(recv)
    if klass == 0:
        return value.Q_UNDEF
    got = dispatch.kind_of(promote(klass), target)
    if got < 0:
        return value.Q_UNDEF
    return value.newbool(got == 1)


def responds_to(recv, sym):
    """respond_to? cached per (class, symbol); an override is per-receiver."""
    if (sym & value.SYMBOL_MASK) != value.SYMBOL_FLAG:
        return value.Q_UNDEF
    klass = value.class_of(recv)
    if klass == 0:
        return value.Q_UNDEF
    got = dispatch.responds(promote(klass), sym)
    if got < 0:
        return value.Q_UNDEF
    return value.newbool(got == 1)


def _real_class_of(recv, mid):
    """Kernel#class's answer: no singleton, mid still Kernel's; else 0."""
    if modules.kernel == 0:
        return 0
    klass = value.class_of(recv)
    if klass == 0:
        return 0
    klass = promote(klass)
    flags = raw_word(klass, value.FLAGS_WORD)
    if flags & value.T_MASK != value.T_CLASS \
            or flags & value.FL_SINGLETON != 0:
        return 0
    if dispatch.lookup(klass, mid) is not None:
        return 0
    if dispatch.owner_of(klass, mid) != modules.kernel:
        return 0
    return klass


def instance_of(recv, target):
    """Kernel#instance_of? is one class compare; a bad target must raise."""
    klass = _real_class_of(recv, INSTANCE_OF_P)
    if klass == 0:
        return value.Q_UNDEF
    if klass == target:
        return value.Q_TRUE
    if value.is_immediate(target):
        return value.Q_UNDEF
    t = raw_word(target, value.FLAGS_WORD) & value.T_MASK
    if t != value.T_CLASS and t != value.T_MODULE:
        return value.Q_UNDEF
    return value.Q_FALSE


def obj_class(recv):
    klass = _real_class_of(recv, CLASS_MID)
    if klass == 0:
        return value.Q_UNDEF
    return klass


def frozen_p(recv):
    """Kernel#frozen? is the FL_FREEZE bit; immediates go back to CRuby."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if _real_class_of(recv, FROZEN_P) == 0:
        return value.Q_UNDEF
    return value.newbool(
        raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0)


def str_eqq(a, b):
    """String#=== is rb_str_equal, the same function as ==."""
    if not value.is_plain_string(a) \
            or not _core_op(value.C_STRING, B_STR_EQQ, EQQ):
        return value.Q_UNDEF
    v = boot.str_eq(a, b)
    if v != value.Q_UNDEF:
        return v
    if value.is_immediate(b) \
            and dispatch.owner_of(promote(value.class_of(b)),
                                  TO_STR) == value.Q_NIL:
        return value.Q_FALSE
    return value.Q_UNDEF


def mod_eqq(a, b):
    """Module#=== is kind_of? with the operands swapped, from the classes."""
    if value.is_immediate(a):
        return value.Q_UNDEF
    t = raw_word(a, value.FLAGS_WORD) & value.T_MASK
    if t != value.T_CLASS and t != value.T_MODULE:
        return value.Q_UNDEF
    ka = promote(value.class_of(a))
    if dispatch.owner_of(ka, EQQ) != value.core_class(value.C_MODULE) \
            or dispatch.lookup(ka, EQQ) is not None:
        return value.Q_UNDEF
    kb = value.class_of(b)
    if kb == 0:
        return value.Q_UNDEF
    got = dispatch.kind_of(promote(kb), a)
    if got < 0:
        return value.Q_UNDEF
    return value.newbool(got == 1)


def eq(a, b):
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a == b)
    if _flt2(a, b, B_FLT_EQ, True):
        return value.newbool(_dbl(a) == _dbl(b))
    # n == nil: Integer#== defers to the arg's == (numeric.c num_equal).
    if b == value.Q_NIL and value.is_fixnum(a) and _int_op(B_INT_EQ) \
            and identity_op(b, EQ):
        return value.Q_FALSE
    v = _str_eq(a, b)
    if v != value.Q_UNDEF:
        return v
    if identity_send(a, EQ):
        return value.newbool(a == b)
    if _ary_eq_false(a, b):
        return value.Q_FALSE
    return value.Q_UNDEF


def neq(a, b):
    # BOP_NEQ is never flagged: vm_opt_neq defers to opt_equality's Integer#==
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a != b)
    if _flt2(a, b, B_FLT_EQ, True):
        return value.newbool(_dbl(a) != _dbl(b))
    # As eq's nil arm: a Fixnum is never nil once both operators are untouched.
    if b == value.Q_NIL and value.is_fixnum(a) and _int_op(B_INT_EQ) \
            and identity_op(b, EQ):
        return value.Q_TRUE
    if value.is_plain_string(a) \
            and dispatch.owns_identity(value.core_class(value.C_STRING), NEQ):
        v = _str_eq(a, b)
        if v != value.Q_UNDEF:
            return value.newbool(v == value.Q_FALSE)
    if identity_send(a, NEQ):
        return value.newbool(a != b)
    if _ary_eq_false(a, b) \
            and dispatch.owns_identity(value.core_class(value.C_ARRAY), NEQ):
        return value.Q_TRUE
    return value.Q_UNDEF


def range_part(recv, mid):
    """Range#begin/#end/#exclude_end?; the shim answers Qundef otherwise."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if mid == BEGIN and _cruby_owns(B_RNG_BEGIN):
        return boot.range_part(recv, boot.RANGE_BEG)
    if mid == END and _cruby_owns(B_RNG_END):
        return boot.range_part(recv, boot.RANGE_END)
    if mid == EXCLUDE_END_P and _cruby_owns(B_RNG_EXCL):
        return boot.range_part(recv, boot.RANGE_EXCL)
    return value.Q_UNDEF


def zero_arg(recv, mid):
    if mid == CLASS_MID:
        return obj_class(recv)
    if mid == FROZEN_P:
        return frozen_p(recv)
    if mid == ABS:
        return int_abs(recv)
    if mid == TO_I:
        return flt_to_i(recv)
    if mid == TO_F:
        return to_f(recv)
    if mid == NAME:
        return sym_name(recv)
    if mid == TO_S:
        v = str_to_s(recv)
        if v != value.Q_UNDEF:
            return v
        v = sym_to_s(recv)
        if v != value.Q_UNDEF:
            return v
        return int_to_s(recv)
    if mid == UMINUS:
        v = flt_uminus(recv)
        if v != value.Q_UNDEF:
            return v
        v = int_uminus(recv)
        if v != value.Q_UNDEF:
            return v
        return str_uminus(recv)
    if mid == POP_MID:
        return ary_pop(recv)
    if mid == SHIFT_MID:
        return ary_shift(recv)
    if mid == FLATTEN_BANG_MID:
        return ary_flatten_bang(recv)
    if mid == FREEZE:
        return ary_hash_freeze(recv)
    if mid == KEYS_MID:
        return hash_keys(recv)
    if mid == EMPTY_P:
        return empty_p(recv)
    if mid == POS_MID or mid == EOS_P_MID or mid == MATCHED_SIZE:
        return ss_zero(recv, mid)
    if mid == DOWNCASE or mid == DOWNCASE_BANG \
            or mid == UPCASE or mid == UPCASE_BANG:
        return str_case(recv, mid)
    if mid == DUP:
        return str_dup(recv)
    if mid == LENGTH or mid == SIZE:
        v = ary_sub_length(recv, mid)
        if v != value.Q_UNDEF:
            return v
        return str_length(recv, mid)
    if mid == BYTESIZE:
        return str_bytesize(recv)
    if mid == ASCII_ONLY_P:
        return str_ascii_only_p(recv)
    return range_part(recv, mid)


def aref(recv, idx):
    """Array[Fixnum] reads in place; a Hash goes straight to the lookup."""
    v = hash_aref(recv, idx)
    if v != value.Q_UNDEF:
        return v
    if value.is_plain_array(recv) and value.is_fixnum(idx) \
            and _ary_op(B_ARY_AREF):
        i = value.fix2int(idx)
        n = value.ary_len(recv)
        if i < 0:
            i += n
        if i >= 0 and i < n:
            return value.ary_at(recv, i)
        return value.Q_NIL
    return int_bitref(recv, idx)


def aset(recv, idx, val):
    """In-place store; growth, sharing and FrozenError go to rb_ary_store."""
    if value.is_plain_array(recv) and value.is_fixnum(idx) \
            and _ary_op(B_ARY_ASET):
        immediate = value.is_immediate(val)
        if immediate or dispatch.barrier.direct:
            n = value.ary_len(recv)
            i = value.fix2int(idx)
            if i < 0:
                i += n
            if i >= 0 and i < n and value.ary_writable(recv):
                value.ary_set(recv, i, val)
                if not immediate:
                    boot.obj_written(recv, val)
                return val
        rubycall.ary_store(recv, value.fix2int(idx), val)
        return val
    v = hash_aset(recv, idx, val)
    if v != value.Q_UNDEF:
        return val
    return value.Q_UNDEF


def length(recv):
    if value.is_plain_array(recv) and _ary_op(B_ARY_LENGTH):
        return value.int2fix(value.ary_len(recv))
    return value.Q_UNDEF


def size(recv):
    if value.is_plain_array(recv) and _ary_op(B_ARY_SIZE):
        return value.int2fix(value.ary_len(recv))
    return value.Q_UNDEF


def empty_p(recv):
    if value.is_plain_array(recv) and _ary_op(B_ARY_EMPTY_P):
        return value.newbool(value.ary_len(recv) == 0)
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if boot.is_hash(recv) and _owned_by_core(recv, value.C_HASH, EMPTY_P):
        return boot.hash_empty_p(recv)
    if boot.is_string(recv) and _owned_by_core(recv, value.C_STRING, EMPTY_P):
        return boot.str_empty_p(recv)
    return value.Q_UNDEF


def nil_p(recv):
    """vm_opt_nil_p; the owner is pristine Kernel, so a redefine is seen."""
    if recv == value.Q_NIL:
        if _cruby_owns(B_NIL_NIL_P) \
                and dispatch.lookup_core(value.core_class(value.C_NILCLASS),
                                         NIL_P) is None:
            return value.Q_TRUE
        return value.Q_UNDEF
    klass = value.class_of(recv)
    if klass == 0 or modules.kernel == 0 or not _cruby_owns(B_KERNEL_NIL_P):
        return value.Q_UNDEF
    klass = promote(klass)
    # The registry too: a module's nil? is invisible to CRuby's owner.
    if dispatch.lookup(klass, NIL_P) is not None:
        return value.Q_UNDEF
    if dispatch.owner_of(klass, NIL_P) != modules.kernel:
        return value.Q_UNDEF
    return value.Q_FALSE


def opt_not(recv):
    # TODO: no BOP flag records #!, so a redefined #! is ignored here.
    return value.newbool(not value.is_true(recv))
