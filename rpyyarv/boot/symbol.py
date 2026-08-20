"""symbol.c: Symbol interning and identifiers."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, INTP, _enter_status,
                                _leave_status, _failed, RubyError)


rb_sym_cstr = _ext('rpyyarv_sym_cstr', [VALUE], rffi.CCHARP, reenters=True)


# No reenters: rejected inside an elidable; nothing here allocates.
rb_intern_ = _ext('rpyyarv_intern', [rffi.CCHARP], VALUE)


rb_sym_new = _ext('rpyyarv_sym_new', [rffi.CCHARP], VALUE, reenters=True)


rb_str_intern = _ext('rpyyarv_str_intern', [VALUE, INTP], VALUE,
                     reenters=True)


rb_sym_to_s_fast = _ext('rpyyarv_sym_to_s', [VALUE], VALUE)


rb_sym_name = _ext('rpyyarv_sym_name', [VALUE], VALUE, reenters=True)


rb_id_name = _ext('rpyyarv_id_name', [VALUE], rffi.CCHARP, reenters=True)


def sym_of(v):
    p = rb_sym_cstr(_v(v))
    if not p:
        raise RubyError('id2name')
    return rffi.charp2str(p)


_intern_memo = {}


def intern(name):
    """rb_intern is idempotent per name; the FFI crossing is paid once."""
    if name in _intern_memo:
        return _intern_memo[name]
    with rffi.scoped_str2charp(name) as c_name:
        r = rffi.cast(lltype.Signed, rb_intern_(c_name))
    _intern_memo[name] = r
    return r


def sym_new(name):
    with rffi.scoped_str2charp(name) as c_name:
        return rffi.cast(lltype.Signed, rb_sym_new(c_name))


def str_intern(v):
    state = _enter_status()
    out = rb_str_intern(rffi.cast(VALUE, v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, out)
    if failed:
        _failed('intern')
    return ret


def id_name(r):
    """rb_id2name; empty when the ID has no name."""
    p = rb_id_name(_v(r))
    if not p:
        return ''
    return rffi.charp2str(p)


def sym_name(sym):
    """The frozen String Symbol#name returns, or Qundef for a dynamic symbol."""
    return rffi.cast(lltype.Signed, rb_sym_name(_v(sym)))


def sym_to_s(v):
    return rffi.cast(lltype.Signed, rb_sym_to_s_fast(_v(v)))
