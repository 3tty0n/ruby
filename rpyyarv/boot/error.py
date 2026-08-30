"""error.c: exception state and error construction."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, INTP, _enter_status,
                                _leave_status, _failed, rb_swap_errinfo)


rb_cleanup_with_error = _ext('rpyyarv_cleanup_with_error', [VALUE], rffi.INT,
                             reenters=True)


rb_arity_error = _ext('rpyyarv_arity_error',
                      [rffi.INT, rffi.INT, rffi.INT, INTP], VALUE,
                      reenters=True)


rb_keyword_error = _ext('rpyyarv_keyword_error',
                        [rffi.CCHARP, VALUE, INTP], VALUE, reenters=True)


rb_local_jump_error = _ext('rpyyarv_local_jump_error',
                           [rffi.CCHARP, VALUE, rffi.INT, INTP], VALUE,
                           reenters=True)


def swap_errinfo(v):
    return rffi.cast(lltype.Signed, rb_swap_errinfo(_v(v)))


def cleanup_with_error(v):
    return rffi.cast(lltype.Signed, rb_cleanup_with_error(_v(v)))


def keyword_error(kind, keys):
    """ArgumentError for 'missing'/'unknown'; keys is an Array of Symbols."""
    state = _enter_status()
    with rffi.scoped_str2charp(kind) as c_kind:
        v = rb_keyword_error(c_kind, _v(keys), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('ArgumentError')
    return ret


def arity_error(given, min_argc, max_argc):
    """The ArgumentError VALUE; -1 for max_argc means unlimited."""
    state = _enter_status()
    v = rb_arity_error(rffi.cast(rffi.INT, given),
                       rffi.cast(rffi.INT, min_argc),
                       rffi.cast(rffi.INT, max_argc), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('ArgumentError')
    return ret


def local_jump_error(mesg, val, reason):
    """The LocalJumpError VALUE; reason is a ruby_tag_type."""
    state = _enter_status()
    with rffi.scoped_str2charp(mesg) as c_mesg:
        v = rb_local_jump_error(c_mesg, _v(val),
                                rffi.cast(rffi.INT, reason), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('LocalJumpError')
    return ret
