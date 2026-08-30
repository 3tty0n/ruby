"""class.c: class/module definition, ancestry, method lookup."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, INTP, _enter_status,
                                _leave_status, _failed, take_errinfo)


rb_patch_method_equality = _ext('rpyyarv_patch_method_equality', [], lltype.Void,
                                reenters=True)


rb_define_class_ = _ext('rpyyarv_define_class',
                        [VALUE, VALUE, VALUE, INTP], VALUE, reenters=True)


rb_define_module_ = _ext('rpyyarv_define_module',
                         [VALUE, VALUE, INTP], VALUE, reenters=True)


rb_class_superclass = _ext('rpyyarv_class_superclass', [VALUE, INTP], VALUE, reenters=True)


rb_singleton_class = _ext('rpyyarv_singleton_class', [VALUE, INTP], VALUE, reenters=True)


rb_method_owner = _ext('rpyyarv_method_owner', [VALUE, VALUE], VALUE,
                       reenters=True)


rb_super_owner = _ext('rpyyarv_super_owner', [VALUE, VALUE, VALUE], VALUE,
                      reenters=True)


rb_responds = _ext('rpyyarv_responds', [VALUE, VALUE], rffi.INT,
                   reenters=True)


rb_class_le = _ext('rpyyarv_class_le', [VALUE, VALUE], rffi.INT,
                   reenters=True)


rb_is_singleton_class = _ext('rpyyarv_is_singleton_class', [VALUE], rffi.INT,
                             reenters=True)


rb_const_defined = _ext('rpyyarv_const_defined',
                        [VALUE, VALUE, rffi.INT], rffi.INT)


rb_method_defined = _ext('rpyyarv_method_defined',
                         [VALUE, VALUE, rffi.INT], rffi.INT, reenters=True)


def const_defined(klass, rid, inherit):
    return rffi.cast(lltype.Signed,
                     rb_const_defined(_v(klass), _v(rid), inherit)) != 0


def method_defined(obj, rid, include_private):
    return rffi.cast(lltype.Signed,
                     rb_method_defined(_v(obj), _v(rid), include_private)) != 0


def method_owner(klass, rid):
    """The module klass resolves rid through, or Qnil when it has none."""
    return rffi.cast(lltype.Signed, rb_method_owner(_v(klass), _v(rid)))


def is_singleton_class(klass):
    return rffi.cast(lltype.Signed, rb_is_singleton_class(_v(klass))) != 0


def class_le(klass, target):
    """Module#<=: 1 below or equal, 0 not, -1 when target is not a Module."""
    return rffi.cast(lltype.Signed, rb_class_le(_v(klass), _v(target)))


def responds(klass, sym):
    """Every instance of klass responds to sym: 1 yes, 0 no, -1 unanswerable."""
    return rffi.cast(lltype.Signed, rb_responds(_v(klass), _v(sym)))


def super_owner(klass, owner, rid):
    """The module `super` from owner's rid reaches next, or Qnil."""
    return rffi.cast(lltype.Signed,
                     rb_super_owner(_v(klass), _v(owner), _v(rid)))


def define_class(cbase, rid, super_v):
    state = _enter_status()
    v = rb_define_class_(_v(cbase), _v(rid), _v(super_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Class.new')
    return ret


def define_module(cbase, rid):
    state = _enter_status()
    v = rb_define_module_(_v(cbase), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Module.new')
    return ret


def class_superclass(klass):
    state = _enter_status()
    v = rb_class_superclass(_v(klass), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        take_errinfo()
        return 0
    return ret


def singleton_class(obj):
    state = _enter_status()
    v = rb_singleton_class(_v(obj), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('singleton_class')
    return ret
