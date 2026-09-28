"""gc.c: mark hooks and the write barrier."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import _ext, _v, VALUE, MARK_HOOK, HANDLE_MARK_HOOK


rb_gc_set_mark_hook = _ext('rpyyarv_gc_set_mark_hook', [MARK_HOOK],
                           lltype.Void, reenters=False)


rb_gc_mark_value = _ext('rpyyarv_gc_mark_value', [VALUE], lltype.Void,
                        reenters=False)


rb_gc_mark_maybe = _ext('rpyyarv_gc_mark_maybe', [VALUE], lltype.Void,
                        reenters=False)


rb_set_handle_mark = _ext('rpyyarv_set_handle_mark_callback',
                          [HANDLE_MARK_HOOK], lltype.Void, reenters=False)


rb_gc_start = _ext('rpyyarv_gc_start', [], lltype.Void, reenters=True)


rb_weak_class_p = _ext('rpyyarv_weak_class_p', [VALUE], rffi.INT,
                       reenters=False)


rb_weak_class_add = _ext('rpyyarv_weak_class_add', [VALUE], lltype.Void,
                         reenters=False)


CLASSES_GONE_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed], lltype.Void))


rb_set_classes_gone_hook = _ext('rpyyarv_set_classes_gone_hook',
                                [CLASSES_GONE_HOOK], lltype.Void,
                                reenters=True)


rb_gone_class = _ext('rpyyarv_gone_class', [lltype.Signed], VALUE,
                     reenters=False)


rb_gc_register = _ext('rpyyarv_gc_register_mark_object', [VALUE], lltype.Void, reenters=True)


# No reenters: sets bits in preallocated bitmaps, reaching no mark callback.
rb_obj_written = _ext('rpyyarv_obj_written', [VALUE, VALUE], lltype.Void,
                      reenters=False)


rb_wb_direct = _ext('rpyyarv_wb_direct', [], rffi.INT, reenters=False)


def obj_written(a, b):
    return rb_obj_written(_v(a), _v(b))


def wb_direct():
    return rffi.cast(lltype.Signed, rb_wb_direct()) != 0


def gc_register(v):
    rb_gc_register(_v(v))


def gc_mark_value(v):
    rb_gc_mark_value(rffi.cast(VALUE, v))


def gc_mark_maybe(w):
    """A word that may or may not be a VALUE; rb_gc_mark_maybe checks."""
    rb_gc_mark_maybe(rffi.cast(VALUE, w))


def gc_start():
    rb_gc_start()


def set_mark_hook(fn):
    rb_gc_set_mark_hook(fn)


def weak_class_p(v):
    return rffi.cast(lltype.Signed, rb_weak_class_p(_v(v))) != 0


def weak_class_add(v):
    rb_weak_class_add(_v(v))


def set_classes_gone_hook(fn):
    rb_set_classes_gone_hook(fn)


def gone_class(i):
    return rffi.cast(lltype.Signed, rb_gone_class(i))


def set_handle_mark(fn):
    """A plain function: rffi builds the enter-RPython-from-C wrapper."""
    rb_set_handle_mark(fn)
