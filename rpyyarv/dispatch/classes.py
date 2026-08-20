"""Class/module creation and adoption from CRuby."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import gcroots
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.error import RubyException
from rpyyarv.rlib import dont_look_inside, raw_word
from rpyyarv.dispatch.core import registry, record_class, Version
from rpyyarv.dispatch.trampoline import _record_ancestry, flush_trampoline_cache


@dont_look_inside
def _reopened(cbase, rid):
    """cbase's own table only, as vm_const_get_under: const_get inherits."""
    try:
        v = boot.const_at(cbase, rid)
    except RubyException:
        return 0
    if value.is_immediate(v) or v == value.Q_UNDEF \
            or raw_word(v, value.FLAGS_WORD) & value.T_MASK != value.T_CLASS:
        return 0
    return v


@dont_look_inside
def define_class(cbase, mid, super_v):
    rid = rubycall.rid(mid)
    klass = 0
    if super_v == 0:
        klass = _reopened(cbase, rid)
    if klass == 0:
        if super_v == 0:
            super_v = value.core_class(value.C_OBJECT)
        klass = boot.define_class(cbase, rid, super_v)
    boot.gc_register(klass)
    parent = boot.class_superclass(klass)
    if parent == 0 or value.is_immediate(parent):
        parent = value.core_class(value.C_OBJECT)
    record_class(klass, parent)
    # An inherited singleton needs meta(Bar) -> meta(Foo) in the map.
    _record_ancestry(boot.singleton_class(klass))
    return klass


@dont_look_inside
def define_module(cbase, mid):
    """No entry in registry.supers: a module has no superclass to walk."""
    mod = boot.define_module(cbase, rubycall.rid(mid))
    registry.module_owned = True
    registry.modules[mod] = True
    registry.version = Version()
    flush_trampoline_cache()
    boot.gc_register(mod)
    gcroots.register_class(mod)
    # `def self.x` and module_function land on the singleton class.
    _record_ancestry(boot.singleton_class(mod))
    return mod


@dont_look_inside
def adopt(mod):
    """Adopt a CRuby-made class/module, exactly as reopening it would."""
    kind = raw_word(mod, value.FLAGS_WORD) & value.T_MASK
    if kind == value.T_CLASS:
        boot.gc_register(mod)
        parent = boot.class_superclass(mod)
        if parent == 0 or value.is_immediate(parent):
            parent = value.core_class(value.C_OBJECT)
        record_class(mod, parent)
        _record_ancestry(boot.singleton_class(mod))
    elif kind == value.T_MODULE:
        registry.module_owned = True
        registry.modules[mod] = True
        registry.version = Version()
        flush_trampoline_cache()
        boot.gc_register(mod)
        gcroots.register_class(mod)
        _record_ancestry(boot.singleton_class(mod))


@dont_look_inside
def alloc(klass):
    # The unprotected shim call: every caller checked is_known_class first.
    return boot.obj_alloc_fast(klass)
