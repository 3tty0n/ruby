"""load.c: require/load resolution and $LOADED_FEATURES."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, VALUEP, INTP,
                                _enter_status, _leave_status, _failed)


rb_require_resolve = _ext('rpyyarv_require_resolve', [VALUE, VALUEP, INTP],
                          rffi.INT, reenters=True)


rb_provide_ = _ext('rpyyarv_provide', [VALUE, INTP], lltype.Void,
                   reenters=True)


rb_absolute_path = _ext('rpyyarv_absolute_path', [VALUE, VALUE, INTP], VALUE,
                        reenters=True)


rb_dir_of = _ext('rpyyarv_dir_of', [VALUE], VALUE, reenters=True)


REQ_LOADED = 0
REQ_RB = 1
REQ_FOREIGN = 2


def dir_of(path):
    """dirname(realpath(path)); Qundef when the path has no realpath."""
    return rffi.cast(lltype.Signed, rb_dir_of(_v(path)))


def require_resolve(fname):
    """(REQ_*, expanded path VALUE); the path is 0 unless REQ_RB."""
    path = 0
    kind = REQ_FOREIGN
    with lltype.scoped_alloc(rffi.CArray(VALUE), 1) as out:
        out[0] = rffi.cast(VALUE, 0)
        with lltype.scoped_alloc(INTP.TO, 1) as state:
            state[0] = rffi.cast(rffi.INT, 0)
            kind = rffi.cast(lltype.Signed,
                             rb_require_resolve(_v(fname), out, state))
        path = rffi.cast(lltype.Signed, out[0])
    if kind != REQ_RB:
        return kind, 0
    return kind, path


def provide(path):
    state = _enter_status()
    rb_provide_(_v(path), state)
    failed = _leave_status(state)
    if failed:
        _failed('$LOADED_FEATURES')


def absolute_path(fname, base):
    state = _enter_status()
    v = rb_absolute_path(_v(fname), _v(base), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('File.absolute_path')
    return ret
