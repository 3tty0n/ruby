"""hash.c: Hash and Set operations."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, INTP, _enter_status,
                                _leave_status, _failed)


rb_hash_aref = _ext('rpyyarv_hash_aref', [VALUE, rffi.CCHARP], VALUE, reenters=True)


rb_hash_new_capa = _ext('rpyyarv_hash_new_capa', [rffi.LONG, INTP], VALUE, reenters=True)


rb_hash_aset_ = _ext('rpyyarv_hash_aset', [VALUE, VALUE, VALUE, INTP],
                     lltype.Void, reenters=True)


rb_hash_resurrect = _ext('rpyyarv_hash_resurrect', [VALUE, INTP], VALUE, reenters=True)


rb_hash_size = _ext('rpyyarv_hash_size', [VALUE], rffi.LONG)


rb_hash_lookup = _ext('rpyyarv_hash_lookup', [VALUE, VALUE, INTP], VALUE, reenters=True)


rb_hash_aref_full = _ext('rpyyarv_hash_aref_v', [VALUE, VALUE, INTP], VALUE,
                         reenters=True)


rb_set_include = _ext('rpyyarv_set_include', [VALUE, VALUE, INTP], VALUE,
                      reenters=True)


rb_hash_pairs = _ext('rpyyarv_hash_pairs', [VALUE, INTP], VALUE,
                     reenters=True)


rb_hash_lookup_fast = _ext('rpyyarv_hash_lookup_fast', [VALUE, VALUE], VALUE)


rb_hash_aset_fast = _ext('rpyyarv_hash_aset_fast', [VALUE, VALUE, VALUE],
                         VALUE)


rb_hash_empty_p = _ext('rpyyarv_hash_empty_p', [VALUE], VALUE)


rb_hash_keys_fast = _ext('rpyyarv_hash_keys_fast', [VALUE, INTP], VALUE,
                         reenters=True)


rb_hash_delete = _ext('rpyyarv_hash_delete', [VALUE, VALUE, INTP],
                      lltype.Void, reenters=True)


rb_hash_keys = _ext('rpyyarv_hash_keys', [VALUE, INTP], VALUE, reenters=True)


rb_to_hash_type = _ext('rpyyarv_to_hash_type', [VALUE, INTP], VALUE, reenters=True)


def hash_aref(hash_v, key):
    with rffi.scoped_str2charp(key) as c_key:
        return rffi.cast(lltype.Signed, rb_hash_aref(_v(hash_v), c_key))


def hash_new(capa):
    state = _enter_status()
    v = rb_hash_new_capa(rffi.cast(rffi.LONG, capa), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash.new')
    return ret


def hash_aset(hash_v, key, val):
    state = _enter_status()
    rb_hash_aset_(_v(hash_v), _v(key), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('Hash#[]=')


def hash_resurrect(hash_v):
    state = _enter_status()
    v = rb_hash_resurrect(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#dup')
    return ret


def hash_size(hash_v):
    return rffi.cast(lltype.Signed, rb_hash_size(_v(hash_v)))


def hash_lookup(hash_v, key):
    """Qundef when the key is absent."""
    state = _enter_status()
    v = rb_hash_lookup(_v(hash_v), _v(key), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#[]')
    return ret


def hash_aref_value(hash_v, key):
    """Hash#[] with defaults, VALUE-keyed unlike hash_aref's C-string key."""
    state = _enter_status()
    v = rb_hash_aref_full(_v(hash_v), _v(key), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#[]')
    return ret


def hash_lookup_fast(hash_v, key):
    """Unprotected: only for a key that cannot call Ruby; Q_UNDEF on miss."""
    return rffi.cast(lltype.Signed, rb_hash_lookup_fast(_v(hash_v), _v(key)))


def hash_aset_fast(hash_v, key, val):
    """Unprotected: only an unfrozen plain Hash, key that cannot call Ruby."""
    rb_hash_aset_fast(_v(hash_v), _v(key), _v(val))


def hash_pairs(hash_v):
    """[k0, v0, k1, v1, ...] of a Hash in entry order, one C call."""
    state = _enter_status()
    v = rb_hash_pairs(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#each')
    return ret


def set_include(set_v, elt):
    """Qundef for anything but a direct core Set."""
    state = _enter_status()
    v = rb_set_include(_v(set_v), _v(elt), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Set#include?')
    return ret


def hash_empty_p(v):
    return rffi.cast(lltype.Signed, rb_hash_empty_p(_v(v)))


def hash_keys_fast(hash_v):
    """[k0, k1, ...] in entry order; not rubycall.hash_keys (error path)."""
    state = _enter_status()
    v = rb_hash_keys_fast(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#keys')
    return ret


def hash_delete(hash_v, key):
    state = _enter_status()
    rb_hash_delete(_v(hash_v), _v(key), state)
    failed = _leave_status(state)
    if failed:
        _failed('Hash#delete')


def hash_keys(hash_v):
    state = _enter_status()
    v = rb_hash_keys(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#keys')
    return ret


def to_hash_type(v):
    state = _enter_status()
    r = rb_to_hash_type(_v(v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, r)
    if failed:
        _failed('Hash()')
    return ret
