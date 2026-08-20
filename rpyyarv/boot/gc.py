"""gc.c: mark hooks and the write barrier."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import _ext, _v, VALUE, MARK_HOOK, HANDLE_MARK_HOOK


rb_gc_set_mark_hook = _ext('rpyyarv_gc_set_mark_hook', [MARK_HOOK],
                           lltype.Void)


rb_gc_mark_value = _ext('rpyyarv_gc_mark_value', [VALUE], lltype.Void)


rb_gc_mark_maybe = _ext('rpyyarv_gc_mark_maybe', [VALUE], lltype.Void)


rb_set_handle_mark = _ext('rpyyarv_set_handle_mark_callback',
                          [HANDLE_MARK_HOOK], lltype.Void)


rb_gc_start = _ext('rpyyarv_gc_start', [], lltype.Void, reenters=True)


rb_gc_register = _ext('rpyyarv_gc_register_mark_object', [VALUE], lltype.Void, reenters=True)


# No reenters: sets bits in preallocated bitmaps, reaching no mark callback.
rb_obj_written = _ext('rpyyarv_obj_written', [VALUE, VALUE], lltype.Void)


rb_wb_direct = _ext('rpyyarv_wb_direct', [], rffi.INT)


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


def set_handle_mark(fn):
    """A plain function: rffi builds the enter-RPython-from-C wrapper."""
    rb_set_handle_mark(fn)
