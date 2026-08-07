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
from rlib import elidable, dont_look_inside, promote, raw_word

# Cycle guard: a superclass chain longer than this is a corrupt map.
MAX_ANCESTORS = 64


class Version(object):
    pass


class MethodEntry(object):
    _immutable_fields_ = ['w_iseq', 'private', 'owner', 'mid']

    def __init__(self, w_iseq, private, owner=0, mid=0):
        self.w_iseq = w_iseq
        # Toplevel defs land on Object as private: only an fcall may reach one.
        self.private = private
        # The class the def landed on, and under which name: invokesuper
        # resumes the lookup above them.
        self.owner = owner
        self.mid = mid


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
    table[mid] = MethodEntry(w_iseq, private, klass, mid)
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


@elidable
def _lookup_super(owner, mid, version):
    """Like _lookup, but starting above owner. No Object fallback beyond what
    the superclass chain itself reaches, or super would find an unrelated
    toplevel def."""
    supers = registry.supers
    methods = registry.methods
    k = supers.get(owner, 0)
    n = 0
    while k != 0 and n < MAX_ANCESTORS:
        table = methods.get(k, None)
        if table is not None:
            entry = table.get(mid, None)
            if entry is not None:
                return entry
        k = supers.get(k, 0)
        n += 1
    return None


def lookup_super(owner, mid):
    return _lookup_super(owner, mid, registry.version)


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


class _Slots(object):
    def __init__(self):
        self.tab = {}       # (shape_id, CRuby ID) -> slot, -1 absent, -2 bail


slots = _Slots()

IV_UNKNOWN = -3


@elidable
def iv_slot(shape_id, rid):
    """Which field slot a shape keeps an ivar in.

    Elidable because a shape node never changes: gaining an ivar moves the
    object to a *different* shape_id, and shape_id is this cache's key, so an
    entry can only ever go unreachable, never stale."""
    key = (shape_id, rid)
    got = slots.tab.get(key, IV_UNKNOWN)
    if got == IV_UNKNOWN:
        got = boot.shape_iv_index(shape_id, rid)
        slots.tab[key] = got
    return got


def ivar_get(obj, mid):
    """T_OBJECT reads compile to a shape guard plus a raw field load; anything
    else falls back to rb_ivar_get."""
    if obj != 0 and (obj & value.IMMEDIATE_MASK) == 0:
        flags = raw_word(obj, value.FLAGS_WORD)
        if (flags & value.T_MASK) == value.T_OBJECT:
            shape_id = promote((flags >> value.SHAPE_SHIFT) & value.SHAPE_MASK)
            slot = iv_slot(shape_id, rubycall.const_rid(mid))
            if slot >= 0:
                if flags & value.ROBJECT_HEAP:
                    return raw_word(raw_word(obj, value.FIELDS_WORD), slot)
                return raw_word(obj, value.FIELDS_WORD + slot)
            if slot == -1:
                return value.Q_NIL
    return _ivar_get_slow(obj, mid)


@dont_look_inside
def _ivar_get_slow(obj, mid):
    return boot.ivar_get(obj, rubycall.rid(mid))


@dont_look_inside
def ivar_set(obj, mid, v):
    # Deliberately still a call: a raw store would skip CRuby's write barrier
    # and leave an old->young reference unremembered by RGenGC.
    boot.ivar_set(obj, rubycall.rid(mid), v)


def check_object_layout():
    """The ivar fast path reads RObject by hand; refuse a CRuby it misreads."""
    got = boot.object_layout()
    want = [value.SHAPE_SHIFT, value.SHAPE_ID_BITS, value.ROBJECT_HEAP,
            value.FIELDS_WORD, value.T_MASK, value.T_OBJECT]
    return got == want


def install():
    """Boot-time: the immediates' classes, and Object as the root of the map."""
    value.install_classes(boot.core_classes())
