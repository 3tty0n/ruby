"""Receiver-class-aware method dispatch: RPyYARV's inline cache.

Methods live in a (klass VALUE -> mid -> entry) registry alongside an
RPython-side superclass map, and lookup is elidable in (klass, mid,
version). A send promotes class_of(recv), so a trace compiles the lookup
away behind one guard_value on the receiver's class word -- a monomorphic
inline cache, with a bridge per extra class at a polymorphic site.
"""

import boot
import gcroots
import rubycall
import value
from rlib import elidable, dont_look_inside

# Cycle guard: a superclass chain longer than this is a corrupt map.
MAX_ANCESTORS = 64


class Version(object):
    pass


class MethodEntry(object):
    _immutable_fields_ = ['w_iseq', 'private']

    def __init__(self, w_iseq, private):
        self.w_iseq = w_iseq
        # Toplevel defs land on Object as private: only an fcall may reach one.
        self.private = private


class Registry(object):
    # Quasi-immutable: reads fold into the trace and definemethod invalidates.
    _immutable_fields_ = ['version?']

    def __init__(self):
        self.methods = {}       # klass VALUE -> {mid: MethodEntry}
        self.supers = {}        # klass VALUE -> superclass VALUE
        self.version = Version()


registry = Registry()


def define(klass, mid, w_iseq, private):
    table = registry.methods.get(klass, None)
    if table is None:
        table = {}
        registry.methods[klass] = table
    table[mid] = MethodEntry(w_iseq, private)
    registry.version = Version()


def record_class(klass, superklass):
    registry.supers[klass] = superklass
    registry.version = Version()
    gcroots.register_class(klass)


def is_known_class(klass):
    return klass in registry.supers


@elidable
def _lookup(klass, mid, version):
    methods = registry.methods
    supers = registry.supers
    k = klass
    n = 0
    while k != 0 and n < MAX_ANCESTORS:
        table = methods.get(k, None)
        if table is not None:
            entry = table.get(mid, None)
            if entry is not None:
                return entry
        k = supers.get(k, 0)
        n += 1
    # Toplevel defs live on Object; reachable from any receiver, as in Ruby.
    table = methods.get(value.core_class(value.C_OBJECT), None)
    if table is not None:
        return table.get(mid, None)
    return None


def lookup(klass, mid):
    return _lookup(klass, mid, registry.version)


@dont_look_inside
def define_class(cbase, mid, super_v):
    """defineclass's class half: create or find it, then remember its parent."""
    if super_v == 0:
        super_v = value.core_class(value.C_OBJECT)
    klass = boot.define_class(cbase, rubycall.rid(mid), super_v)
    boot.gc_register(klass)
    parent = boot.class_superclass(klass)
    if parent == 0 or value.is_immediate(parent):
        parent = value.core_class(value.C_OBJECT)
    record_class(klass, parent)
    return klass


@dont_look_inside
def alloc(klass):
    return boot.obj_alloc(klass)


@dont_look_inside
def const_get(klass, mid):
    return boot.const_get(klass, rubycall.rid(mid))


@dont_look_inside
def const_set(klass, mid, v):
    boot.const_set(klass, rubycall.rid(mid), v)


@dont_look_inside
def ivar_get(obj, mid):
    return boot.ivar_get(obj, rubycall.rid(mid))


@dont_look_inside
def ivar_set(obj, mid, v):
    boot.ivar_set(obj, rubycall.rid(mid), v)


def install():
    """Boot-time: the immediates' classes, and Object as the root of the map."""
    value.install_classes(boot.core_classes())
