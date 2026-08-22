"""array.c: Array construction, access, and mutation."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, VALUEP, INTP, MAX_ARGC,
                                _enter_status, _leave_status, _enter_argv,
                                _leave_argv, _failed)


rb_ary_len = _ext('rpyyarv_ary_len', [VALUE], rffi.LONG)


rb_ary_entry = _ext('rpyyarv_ary_entry', [VALUE, rffi.LONG], VALUE, reenters=True)


rb_ary_subseq = _ext('rpyyarv_ary_subseq', [VALUE, rffi.LONG, rffi.LONG],
                     VALUE, reenters=True)


rb_ary_new = _ext('rpyyarv_ary_new', [rffi.INT, VALUEP], VALUE, reenters=True)


rb_array_layout = _ext('rpyyarv_array_layout', [INTP], lltype.Void)


rb_ary_resurrect = _ext('rpyyarv_ary_resurrect', [VALUE, INTP], VALUE, reenters=True)


rb_ary_store_ = _ext('rpyyarv_ary_store', [VALUE, rffi.LONG, VALUE, INTP],
                     lltype.Void, reenters=True)


rb_ary_new_capa = _ext('rpyyarv_ary_new_capa', [rffi.LONG, INTP], VALUE, reenters=True)


rb_ary_store_fresh = _ext('rpyyarv_ary_store_fresh', [VALUE, rffi.LONG, VALUE],
                          lltype.Void, reenters=True)


rb_ary_new_capa_fast = _ext('rpyyarv_ary_new_capa_fast', [rffi.LONG], VALUE, reenters=True)


rb_ary_new_filled_fast = _ext('rpyyarv_ary_new_filled_fast', [rffi.LONG, VALUE],
                              VALUE, reenters=True)


rb_ary_new_filled = _ext('rpyyarv_ary_new_filled', [rffi.LONG, VALUE, INTP],
                         VALUE, reenters=True)


rb_ary_cat = _ext('rpyyarv_ary_cat', [VALUE, rffi.INT, VALUEP, INTP],
                  lltype.Void, reenters=True)


rb_ary_pop_fast = _ext('rpyyarv_ary_pop_fast', [VALUE], VALUE)


rb_ary_push1 = _ext('rpyyarv_ary_push1', [VALUE, VALUE], VALUE)


rb_ary_shift_fast = _ext('rpyyarv_ary_shift_fast', [VALUE], VALUE)


rb_ary_unshift1 = _ext('rpyyarv_ary_unshift1', [VALUE, VALUE], VALUE)


rb_ary_hash_freeze = _ext('rpyyarv_ary_hash_freeze', [VALUE], VALUE)

rb_obj_freeze = _ext('rpyyarv_obj_freeze', [VALUE], VALUE)


rb_ary_flatten_bang1 = _ext('rpyyarv_ary_flatten_bang1', [VALUE], VALUE)


rb_splat_array = _ext('rpyyarv_splat_array', [VALUE, rffi.INT, INTP], VALUE, reenters=True)


rb_concat_array = _ext('rpyyarv_concat_array', [VALUE, VALUE, rffi.INT, INTP], VALUE, reenters=True)


rb_ary_to_ary = _ext('rpyyarv_ary_to_ary', [VALUE, INTP], VALUE,
                     reenters=True)


def ary_len(v):
    return rffi.cast(lltype.Signed, rb_ary_len(_v(v)))


def ary_entry(v, i):
    return rffi.cast(lltype.Signed,
                     rb_ary_entry(_v(v), rffi.cast(rffi.LONG, i)))


def ary_subseq(v, beg, length):
    return rffi.cast(lltype.Signed,
                     rb_ary_subseq(_v(v), rffi.cast(rffi.LONG, beg),
                                   rffi.cast(rffi.LONG, length)))


def ary_new(values):
    n = len(values)
    if n > MAX_ARGC:
        return _ary_new_chunked(values)
    buf = _enter_argv(n)
    i = 0
    while i < n:
        buf[i] = rffi.cast(VALUE, values[i])
        i += 1
    ret = rffi.cast(lltype.Signed, rb_ary_new(rffi.cast(rffi.INT, n), buf))
    _leave_argv(buf)
    return ret


def _ary_new_chunked(values):
    """`ary` is an RPython local; the conservative stack scan covers it."""
    n = len(values)
    ary = 0
    state = _enter_status()
    ary = rffi.cast(lltype.Signed,
                    rb_ary_new_capa(rffi.cast(rffi.LONG, n), state))
    failed = _leave_status(state)
    if failed:
        _failed('Array.new')
    at = 0
    while at < n:
        count = n - at
        if count > MAX_ARGC:
            count = MAX_ARGC
        with lltype.scoped_alloc(rffi.CArray(VALUE), count + 1) as buf:
            i = 0
            while i < count:
                buf[i] = rffi.cast(VALUE, values[at + i])
                i += 1
            state = _enter_status()
            rb_ary_cat(rffi.cast(VALUE, ary), rffi.cast(rffi.INT, count),
                       buf, state)
            failed = _leave_status(state)
        if failed:
            _failed('Array#concat')
        at += count
    return ary


def ary_resurrect(ary):
    state = _enter_status()
    v = rb_ary_resurrect(_v(ary), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array#dup')
    return ret


def ary_store(ary, idx, val):
    state = _enter_status()
    rb_ary_store_(_v(ary), rffi.cast(rffi.LONG, idx), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('Array#[]=')


def ary_store_fresh(ary, idx, val):
    """No status cell: the shim call cannot raise."""
    rb_ary_store_fresh(_v(ary), rffi.cast(rffi.LONG, idx), _v(val))


def ary_new_capa_fast(capa):
    return rffi.cast(lltype.Signed, rb_ary_new_capa_fast(rffi.cast(rffi.LONG, capa)))


def ary_new_filled_fast(n, val):
    return rffi.cast(lltype.Signed,
                     rb_ary_new_filled_fast(rffi.cast(rffi.LONG, n), _v(val)))


def ary_new_capa(capa):
    state = _enter_status()
    v = rb_ary_new_capa(rffi.cast(rffi.LONG, capa), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array.new')
    return ret


def ary_new_filled(n, val):
    state = _enter_status()
    v = rb_ary_new_filled(rffi.cast(rffi.LONG, n), _v(val), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array.new')
    return ret


def ary_to_ary(obj):
    """to_ary when the object has one, otherwise a one-element Array."""
    state = _enter_status()
    v = rb_ary_to_ary(_v(obj), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('to_ary')
    return ret


ARRAY_LAYOUT_N = 10


def array_layout():
    out = [0] * ARRAY_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, ARRAY_LAYOUT_N) as buf:
        rb_array_layout(buf)
        for i in range(ARRAY_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


def ary_pop(v):
    return rffi.cast(lltype.Signed, rb_ary_pop_fast(_v(v)))


def ary_push1(v, elt):
    return rffi.cast(lltype.Signed, rb_ary_push1(_v(v), _v(elt)))


def ary_shift(v):
    return rffi.cast(lltype.Signed, rb_ary_shift_fast(_v(v)))


def ary_unshift1(v, elt):
    return rffi.cast(lltype.Signed, rb_ary_unshift1(_v(v), _v(elt)))


def ary_hash_freeze(v):
    return rffi.cast(lltype.Signed, rb_ary_hash_freeze(_v(v)))


def obj_freeze(v):
    return rffi.cast(lltype.Signed, rb_obj_freeze(_v(v)))


def ary_flatten_bang1(v):
    return rffi.cast(lltype.Signed, rb_ary_flatten_bang1(_v(v)))


def splat_array(ary, flag):
    state = _enter_status()
    v = rb_splat_array(_v(ary), rffi.cast(rffi.INT, flag), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('to_a')
    return ret


def concat_array(ary1, ary2, to):
    state = _enter_status()
    v = rb_concat_array(_v(ary1), _v(ary2), rffi.cast(rffi.INT, 1 if to else 0),
                        state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('to_a')
    return ret
