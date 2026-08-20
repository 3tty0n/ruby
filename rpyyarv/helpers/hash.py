"""Hash and Set fast paths."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import value
from rpyyarv.rlib import promote, raw_word
from rpyyarv.helpers.core import *
from rpyyarv.helpers.core import _core_op, _cruby_owns, _owned_by_core


def _hash_key_cannot_reenter(key):
    """Immediates and plain Strings hash in C: no Ruby, so no rb_protect."""
    return value.is_immediate(key) or value.is_plain_string(key)


def hash_aref(recv, key):
    """Hash#[] in one protected call, the default value or proc included."""
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    if not _core_op(value.C_HASH, B_HASH_AREF, AREF):
        return value.Q_UNDEF
    if _hash_key_cannot_reenter(key):
        v = boot.hash_lookup_fast(recv, key)
        if v != value.Q_UNDEF:
            return v
        # A miss still consults the default below, under rb_protect.
    return boot.hash_aref_value(recv, key)


def hash_key_p(recv, key, mid):
    """Hash#key? through Hash#[]'s lookup: absence is the Qundef of a miss."""
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    bit = B_HASH_KEY if mid == KEY_P else B_HASH_HAS_KEY
    if not _core_op(value.C_HASH, bit, mid):
        return value.Q_UNDEF
    if _hash_key_cannot_reenter(key):
        return value.newbool(boot.hash_lookup_fast(recv, key) != value.Q_UNDEF)
    return value.newbool(boot.hash_lookup(recv, key) != value.Q_UNDEF)


def hash_aset(recv, key, val):
    """Hash#[]= in one protected call; the frozen check raises inside it."""
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    if not _core_op(value.C_HASH, B_HASH_ASET, ASET):
        return value.Q_UNDEF
    if _hash_key_cannot_reenter(key) \
            and raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE == 0:
        boot.hash_aset_fast(recv, key, val)
        return val
    boot.hash_aset(recv, key, val)
    return val


def set_include(recv, elt):
    """Set#include? on a direct core Set; the guard is only redefinition."""
    if value.is_immediate(recv) or not _cruby_owns(B_SET_INCLUDE):
        return value.Q_UNDEF
    if dispatch.lookup(promote(value.class_of(recv)), INCLUDE_P) is not None:
        return value.Q_UNDEF
    return boot.set_include(recv, elt)


def hash_keys(recv):
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_HASH, KEYS_MID):
        return value.Q_UNDEF
    return boot.hash_keys_fast(recv)
