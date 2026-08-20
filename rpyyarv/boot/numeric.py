"""numeric.c: Integer, Float, and Range construction."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, INTP, _enter_status,
                                _leave_status, _failed)


rb_int2inum = _ext('rpyyarv_int2inum', [rffi.LONG], VALUE, reenters=True)


rb_float_new = _ext('rpyyarv_float_new', [rffi.DOUBLE], VALUE, reenters=True)


rb_float_layout = _ext('rpyyarv_float_layout', [INTP], lltype.Void)


rb_range_new_ = _ext('rpyyarv_range_new', [VALUE, VALUE, rffi.INT, INTP],
                     VALUE, reenters=True)


def range_new(low, high, excl):
    state = _enter_status()
    v = rb_range_new_(_v(low), _v(high), rffi.cast(rffi.INT, excl), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Range.new')
    return ret


def int2inum(n):
    return rffi.cast(lltype.Signed, rb_int2inum(rffi.cast(rffi.LONG, n)))


def float_new(d):
    return rffi.cast(lltype.Signed, rb_float_new(rffi.cast(rffi.DOUBLE, d)))


FLOAT_LAYOUT_N = 3


def float_layout():
    out = [0] * FLOAT_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, FLOAT_LAYOUT_N) as buf:
        rb_float_layout(buf)
        for i in range(FLOAT_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out
