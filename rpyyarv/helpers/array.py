"""Array fast paths."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import value
from rpyyarv.rlib import promote, raw_word
from rpyyarv.helpers.core import *
from rpyyarv.helpers.core import _ary_op, _cruby_owns, _owned_by_core


def ary_pop(recv):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, POP_MID):
        return value.Q_UNDEF
    return boot.ary_pop(recv)


def ary_push_one(recv, arg):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, PUSH_MID):
        return value.Q_UNDEF
    return boot.ary_push1(recv, arg)


def ary_shift(recv):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, SHIFT_MID):
        return value.Q_UNDEF
    return boot.ary_shift(recv)


def ary_unshift1(recv, arg):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, UNSHIFT_MID):
        return value.Q_UNDEF
    return boot.ary_unshift1(recv, arg)


def ary_flatten_bang(recv):
    """Array#flatten! for Array elements only; a #to_ary quacker is a gap."""
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, FLATTEN_BANG_MID):
        return value.Q_UNDEF
    return boot.ary_flatten_bang1(recv)


def ary_hash_freeze(recv):
    """Array#freeze / Hash#freeze: OBJ_FREEZE_RAW cannot re-enter Ruby."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if value.is_plain_array(recv):
        klass_i = value.C_ARRAY
    elif raw_word(recv, value.KLASS_WORD) == value.core_class(value.C_HASH):
        klass_i = value.C_HASH
    else:
        return value.Q_UNDEF
    if not _owned_by_core(recv, klass_i, FREEZE):
        return value.Q_UNDEF
    return boot.ary_hash_freeze(recv)


def ary_sub_aref(recv, idx):
    """Array#[] on a subclass keeping Array's; rb_ary_entry handles bounds."""
    if value.is_immediate(recv) or not value.is_fixnum(idx) \
            or not boot.is_array(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, AREF):
        return value.Q_UNDEF
    return boot.ary_entry(recv, value.fix2int(idx))


def ary_sub_length(recv, mid):
    """Array#length/#size on a subclass that kept Array's."""
    if value.is_immediate(recv) or not boot.is_array(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, mid):
        return value.Q_UNDEF
    return value.int2fix(boot.ary_len(recv))


def _ary_eq_false(a, b):
    """rb_ary_equal (array.c:5382) is false for a non-Array with no to_ary."""
    if not (value.is_plain_array(a) and value.is_immediate(b)):
        return False
    # TODO: a respond_to? claiming an undefined to_ary reads as no to_ary.
    if dispatch.owner_of(promote(value.class_of(b)), TO_ARY) != value.Q_NIL:
        return False
    klass = value.core_class(value.C_ARRAY)
    return (dispatch.owner_of(klass, EQ) == klass
            and dispatch.lookup_core(klass, EQ) is None)


def ary_new_pristine(recv):
    """Array.new and Array#initialize both still CRuby's, on both sides."""
    return (recv == value.core_class(value.C_ARRAY)
            and _cruby_owns(B_ARY_NEW) and _cruby_owns(B_ARY_INITIALIZE)
            and dispatch.lookup_core(recv, INITIALIZE) is None)


def check_array_layout():
    """Array fast paths read RArray by hand; refuse a CRuby they misread."""
    got = boot.array_layout()
    want = [value.ARY_EMBED_FLAG, value.ARY_EMBED_LEN_SHIFT,
            value.ARY_EMBED_LEN_MASK, value.ARY_HEAP_LEN_WORD,
            value.ARY_HEAP_PTR_WORD, value.ARY_EMBED_WORD,
            value.ARY_SHARED_FLAG, value.ARY_SHARED_ROOT_FLAG,
            value.ARY_HEAP_CAPA_WORD, value.T_ARRAY]
    return got == want


def check_struct_layout():
    """The Struct fast paths read RStruct by hand; refuse a bad CRuby."""
    got = boot.struct_layout()
    want = [value.STRUCT_EMBED_LEN_MASK, value.STRUCT_EMBED_LEN_SHIFT,
            value.STRUCT_HEAP_LEN_WORD, value.STRUCT_HEAP_PTR_WORD,
            value.STRUCT_EMBED_WORD, value.T_STRUCT]
    return got == want


def _ary_reverse(recv, lo, hi):
    """Permutes what the array already holds, so no write barrier is due."""
    hi -= 1
    while lo < hi:
        a = value.ary_at(recv, lo)
        value.ary_set(recv, lo, value.ary_at(recv, hi))
        value.ary_set(recv, hi, a)
        lo += 1
        hi -= 1


def ary_rotate_bang(recv, cnt):
    """Three reversals in place; rb_ary_rotate keeps the odd cases."""
    if not value.is_plain_array(recv) or not value.is_fixnum(cnt) \
            or not value.ary_writable(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, ROTATE_BANG):
        return value.Q_UNDEF
    n = value.ary_len(recv)
    if n > 1:
        k = value.fix2int(cnt) % n
        if k < 0:
            k += n
        if k != 0:
            _ary_reverse(recv, 0, k)
            _ary_reverse(recv, k, n)
            _ary_reverse(recv, 0, n)
    return recv


def ary_splice_set(recv, beg, cnt, src):
    """a[i, n] = ary only where it is an in-place copy of the same length."""
    if not value.is_plain_array(recv) or not value.is_plain_array(src) \
            or not value.is_fixnum(beg) or not value.is_fixnum(cnt):
        return value.Q_UNDEF
    if not _ary_op(B_ARY_ASET) or not value.ary_writable(recv):
        return value.Q_UNDEF
    i = value.fix2int(beg)
    n = value.fix2int(cnt)
    if i < 0 or n < 0 or i + n > value.ary_len(recv) \
            or value.ary_len(src) != n or src == recv:
        return value.Q_UNDEF
    direct = dispatch.barrier.direct
    j = 0
    while j < n:
        if not direct and not value.is_immediate(value.ary_at(src, j)):
            return value.Q_UNDEF
        j += 1
    j = 0
    while j < n:
        v = value.ary_at(src, j)
        value.ary_set(recv, i + j, v)
        if not value.is_immediate(v):
            boot.obj_written(recv, v)
        j += 1
    return src
