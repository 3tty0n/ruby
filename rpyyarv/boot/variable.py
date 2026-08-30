"""variable.c: constants, ivars, cvars, gvars, aliasing."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, INTP, _enter_status,
                                _leave_status, _failed)


rb_const_get_ = _ext('rpyyarv_const_get', [VALUE, VALUE, INTP], VALUE, reenters=True)


rb_const_get_from_ = _ext('rpyyarv_const_get_from', [VALUE, VALUE, INTP],
                          VALUE, reenters=True)


rb_const_at_ = _ext('rpyyarv_const_at', [VALUE, VALUE, INTP], VALUE,
                    reenters=True)


rb_const_set_ = _ext('rpyyarv_const_set', [VALUE, VALUE, VALUE, INTP],
                     lltype.Void, reenters=True)


rb_ivar_get_ = _ext('rpyyarv_ivar_get', [VALUE, VALUE, INTP], VALUE, reenters=True)


rb_ivar_set_ = _ext('rpyyarv_ivar_set', [VALUE, VALUE, VALUE, INTP],
                    lltype.Void, reenters=True)


rb_gvar_get_ = _ext('rpyyarv_gvar_get', [rffi.CCHARP, INTP], VALUE, reenters=True)


rb_gvar_set_ = _ext('rpyyarv_gvar_set', [rffi.CCHARP, VALUE, INTP],
                    lltype.Void, reenters=True)


rb_alias_variable = _ext('rpyyarv_alias_variable', [VALUE, VALUE, INTP],
                         VALUE, reenters=True)


rb_cvar_get = _ext('rpyyarv_cvar_get', [VALUE, VALUE, INTP], VALUE,
                   reenters=True)


rb_cvar_set = _ext('rpyyarv_cvar_set', [VALUE, VALUE, VALUE, INTP],
                   lltype.Void, reenters=True)


rb_cvar_defined = _ext('rpyyarv_cvar_defined', [VALUE, VALUE], rffi.INT,
                       reenters=True)


rb_class_ivar_get = _ext('rpyyarv_class_ivar_get', [VALUE, VALUE], VALUE)


rb_ivar_defined = _ext('rpyyarv_ivar_defined', [VALUE, VALUE], rffi.INT)


rb_gvar_defined_ = _ext('rpyyarv_gvar_defined', [rffi.CCHARP], rffi.INT)


def gvar_defined(name):
    with rffi.scoped_str2charp(name) as c_name:
        return rffi.cast(lltype.Signed, rb_gvar_defined_(c_name)) != 0


def gvar_get(name):
    state = _enter_status()
    with rffi.scoped_str2charp(name) as c_name:
        v = rb_gvar_get_(c_name, state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed(name)
    return ret


def gvar_set(name, val):
    state = _enter_status()
    with rffi.scoped_str2charp(name) as c_name:
        rb_gvar_set_(c_name, _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed(name)


def class_ivar_get(obj, rid):
    return rffi.cast(lltype.Signed, rb_class_ivar_get(_v(obj), _v(rid)))


def ivar_defined(obj, rid):
    return rffi.cast(lltype.Signed, rb_ivar_defined(_v(obj), _v(rid))) != 0


def cvar_get(klass, rid):
    state = _enter_status()
    v = rb_cvar_get(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('class variable')
    return ret


def cvar_set(klass, rid, val):
    state = _enter_status()
    rb_cvar_set(_v(klass), _v(rid), _v(val), state)
    if _leave_status(state):
        _failed('class variable')


def cvar_defined(klass, rid):
    return rffi.cast(lltype.Signed,
                     rb_cvar_defined(_v(klass), _v(rid))) != 0


def const_get(klass, rid):
    state = _enter_status()
    v = rb_const_get_(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('const_get')
    return ret


def const_get_from(klass, rid):
    """Qualified A::B: a hit on Object does not count (variable.c:3470)."""
    state = _enter_status()
    v = rb_const_get_from_(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('const_get')
    return ret


def const_at(klass, rid):
    state = _enter_status()
    v = rb_const_at_(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('const_at')
    return ret


def const_set(klass, rid, val):
    state = _enter_status()
    rb_const_set_(_v(klass), _v(rid), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('const_set')


def ivar_get(obj, rid):
    state = _enter_status()
    v = rb_ivar_get_(_v(obj), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('instance_variable_get')
    return ret


def ivar_set(obj, rid, val):
    state = _enter_status()
    rb_ivar_set_(_v(obj), _v(rid), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('instance_variable_set')


def alias_variable(sym1, sym2):
    """`alias $new $old`, as vm.c's core#set_variable_alias does it."""
    state = _enter_status()
    rb_alias_variable(_v(sym1), _v(sym2), state)
    failed = _leave_status(state)
    if failed:
        _failed('alias')
