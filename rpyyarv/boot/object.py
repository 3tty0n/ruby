"""object.c: type predicates, allocation, shapes, struct access."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, VALUEP, INTP,
                                _enter_status, _leave_status, _failed)


rb_inspect_cstr = _ext('rpyyarv_inspect_cstr', [VALUE], rffi.CCHARP, reenters=True)


rb_is_array = _ext('rpyyarv_is_array', [VALUE], rffi.INT)


rb_is_symbol = _ext('rpyyarv_is_symbol', [VALUE], rffi.INT)


rb_is_fixnum = _ext('rpyyarv_is_fixnum', [VALUE], rffi.INT)


rb_is_string = _ext('rpyyarv_is_string', [VALUE], rffi.INT)


rb_is_hash = _ext('rpyyarv_is_hash', [VALUE], rffi.INT)


rb_is_nil = _ext('rpyyarv_is_nil', [VALUE], rffi.INT)


rb_is_true = _ext('rpyyarv_is_true', [VALUE], rffi.INT)


rb_is_false = _ext('rpyyarv_is_false', [VALUE], rffi.INT)


rb_num2long = _ext('rpyyarv_num2long', [VALUE], rffi.LONG, reenters=True)


rb_special_consts = _ext('rpyyarv_special_consts',
                         [VALUEP, VALUEP, VALUEP, VALUEP], lltype.Void)


rb_core_classes = _ext('rpyyarv_core_classes', [VALUEP], lltype.Void)


# marks: rb_obj_alloc runs no Ruby code; only a GC can re-enter us.
rb_obj_alloc = _ext('rpyyarv_obj_alloc', [VALUE, INTP], VALUE, marks=True)


rb_obj_alloc_fast = _ext('rpyyarv_obj_alloc_fast', [VALUE], VALUE, marks=True)


rb_alloc_default = _ext('rpyyarv_alloc_default', [VALUE], VALUE, marks=True)


rb_shape_iv_index = _ext('rpyyarv_shape_iv_index', # no reenters: see rb_intern_
                         [rffi.UINT, VALUE, INTP], rffi.INT)


rb_shape_add_ivar_fits = _ext('rpyyarv_shape_add_ivar_fits',
                              [rffi.UINT, rffi.UINT, VALUE, INTP], rffi.INT)


rb_object_layout = _ext('rpyyarv_object_layout', [INTP], lltype.Void)


rb_is_class = _ext('rpyyarv_is_class', [VALUE], rffi.INT)


rb_obj_is_kind_of = _ext('rpyyarv_obj_is_kind_of', [VALUE, VALUE, INTP],
                         rffi.INT, reenters=True)


# No reenters: reads two struct fields after a type test, allocating nothing.
rb_range_part = _ext('rpyyarv_range_part', [VALUE, rffi.INT], VALUE)


rb_struct_member_index = _ext('rpyyarv_struct_member_index',
                              [VALUE, VALUE], rffi.INT, reenters=True)


rb_struct_layout = _ext('rpyyarv_struct_layout', [INTP], lltype.Void)


rb_struct_arity = _ext('rpyyarv_struct_arity', [VALUE], rffi.LONG,
                       reenters=True)


rb_struct_alloc_ = _ext('rpyyarv_struct_alloc', [VALUE], VALUE, reenters=True)


rb_struct_get = _ext('rpyyarv_struct_get', [VALUE, rffi.INT], VALUE)


rb_struct_set = _ext('rpyyarv_struct_set', [VALUE, rffi.INT, VALUE],
                     lltype.Void)


NCLASS = 14


def inspect(v):
    p = rb_inspect_cstr(_v(v))
    if not p:
        return '<inspect failed>'
    return rffi.charp2str(p)


def is_array(v):
    return rffi.cast(lltype.Signed, rb_is_array(_v(v))) != 0


def is_symbol(v):
    return rffi.cast(lltype.Signed, rb_is_symbol(_v(v))) != 0


def is_fixnum(v):
    return rffi.cast(lltype.Signed, rb_is_fixnum(_v(v))) != 0


def is_string(v):
    return rffi.cast(lltype.Signed, rb_is_string(_v(v))) != 0


def is_hash(v):
    return rffi.cast(lltype.Signed, rb_is_hash(_v(v))) != 0


def is_nil(v):
    return rffi.cast(lltype.Signed, rb_is_nil(_v(v))) != 0


def is_true(v):
    return rffi.cast(lltype.Signed, rb_is_true(_v(v))) != 0


def is_false(v):
    return rffi.cast(lltype.Signed, rb_is_false(_v(v))) != 0


def num2long(v):
    return rffi.cast(lltype.Signed, rb_num2long(_v(v)))


def special_consts():
    """(Qfalse, Qnil, Qtrue, FIXNUM_FLAG) as this libruby defines them."""
    with lltype.scoped_alloc(rffi.CArray(VALUE), 4) as out:
        rb_special_consts(rffi.ptradd(out, 0), rffi.ptradd(out, 1),
                          rffi.ptradd(out, 2), rffi.ptradd(out, 3))
        return (rffi.cast(lltype.Signed, out[0]),
                rffi.cast(lltype.Signed, out[1]),
                rffi.cast(lltype.Signed, out[2]),
                rffi.cast(lltype.Signed, out[3]))


def core_classes():
    with lltype.scoped_alloc(rffi.CArray(VALUE), NCLASS) as out:
        rb_core_classes(out)
        result = [0] * NCLASS
        i = 0
        while i < NCLASS:
            result[i] = rffi.cast(lltype.Signed, out[i])
            i += 1
        return result


RANGE_BEG = 0
RANGE_END = 1
RANGE_EXCL = 2


def range_part(v, which):
    """One Range field, or Qundef when v is not a direct Range."""
    return rffi.cast(lltype.Signed,
                     rb_range_part(_v(v), rffi.cast(rffi.INT, which)))


def struct_member_index(klass, rid):
    return rffi.cast(lltype.Signed,
                     rb_struct_member_index(_v(klass), _v(rid)))


def struct_get(obj, index):
    return rffi.cast(lltype.Signed,
                     rb_struct_get(_v(obj), rffi.cast(rffi.INT, index)))


def struct_set(obj, index, v):
    rb_struct_set(_v(obj), rffi.cast(rffi.INT, index), _v(v))


def struct_arity(klass):
    """Members of a positional Struct class, -1 otherwise; asked once."""
    return rffi.cast(lltype.Signed, rb_struct_arity(_v(klass)))


def struct_alloc(klass):
    """Unprotected: only for a class struct_arity has already blessed."""
    return rffi.cast(lltype.Signed, rb_struct_alloc_(_v(klass)))


def obj_alloc_fast(klass):
    return rffi.cast(lltype.Signed, rb_obj_alloc_fast(_v(klass)))


def alloc_default(klass):
    """Unprotected: Qundef unless the shim knows the alloc cannot raise."""
    return rffi.cast(lltype.Signed, rb_alloc_default(_v(klass)))


def obj_alloc(klass):
    state = _enter_status()
    v = rb_obj_alloc(_v(klass), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('allocate')
    return ret


STRUCT_LAYOUT_N = 6


def struct_layout():
    out = [0] * STRUCT_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, STRUCT_LAYOUT_N) as buf:
        rb_struct_layout(buf)
        for i in range(STRUCT_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


LAYOUT_N = 14


def object_layout():
    out = [0] * LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, LAYOUT_N) as buf:
        rb_object_layout(buf)
        for i in range(LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


def shape_iv_index(shape_id, rid):
    """Slot holding rid in shape_id: >= 0 found, -1 absent, -2 no fast path."""
    with lltype.scoped_alloc(INTP.TO, 1) as idx:
        idx[0] = rffi.cast(rffi.INT, -1)
        found = rffi.cast(lltype.Signed,
                          rb_shape_iv_index(rffi.cast(rffi.UINT, shape_id),
                                            _v(rid), idx))
        slot = rffi.cast(lltype.Signed, idx[0])
    if found == 1:
        return slot
    if found == 0:
        return -1
    return -2


def shape_add_ivar_slot(before, after, rid):
    """Slot a raw store may put rid in going before->after, else -1."""
    with lltype.scoped_alloc(INTP.TO, 1) as idx:
        idx[0] = rffi.cast(rffi.INT, -1)
        ok = rffi.cast(lltype.Signed,
                       rb_shape_add_ivar_fits(rffi.cast(rffi.UINT, before),
                                              rffi.cast(rffi.UINT, after),
                                              _v(rid), idx))
        slot = rffi.cast(lltype.Signed, idx[0])
    if ok == 1:
        return slot
    return -1


def is_class(v):
    return rffi.cast(lltype.Signed, rb_is_class(_v(v))) != 0


def obj_is_kind_of(obj, klass):
    state = _enter_status()
    r = rffi.cast(lltype.Signed, rb_obj_is_kind_of(_v(obj), _v(klass),
                                                   state))
    failed = _leave_status(state)
    if failed:
        _failed('kind_of?')
    return r != 0
