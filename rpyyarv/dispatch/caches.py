"""Elidable lookup caches: owner, respond_to?, kind_of?, struct, ivar slot."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import gcroots
from rpyyarv import symbols
from rpyyarv import rubycall
from rpyyarv.rlib import elidable, dont_look_inside
from rpyyarv.dispatch.core import registry, Version


class _Owners(object):
    # Tagged by registry.version: one quasi-immutable, one guard.
    def __init__(self):
        self.tab = {}       # (klass VALUE, mid) -> owning module VALUE
        self.stab = {}      # the same, for the module above that one
        self.rtab = {}  # (klass VALUE, Symbol VALUE) -> respond_to? per inst
        self.ktab = {}  # (klass VALUE, module VALUE) -> kind_of? per instance
        self.invalidations = 0


owners = _Owners()

OWNER_UNKNOWN = -1


def invalidate_owners():
    """rb_clear_method_cache: def, undef, alias, include, prepend all hit."""
    if len(owners.tab) == 0 and len(owners.stab) == 0 \
            and len(owners.rtab) == 0 and len(owners.ktab) == 0:
        return
    owners.invalidations += 1
    debug.note_invalidation(owners.invalidations)
    owners.tab = {}
    owners.stab = {}
    owners.rtab = {}
    owners.ktab = {}
    registry.version = Version()
    flush_trampoline_cache()


@elidable
def _owner_of(klass, mid, version):
    return owners.tab.get((klass, mid), OWNER_UNKNOWN)


# Filling never bumps the version: only a real redefinition invalidates.
@dont_look_inside
def _fill_owner(klass, mid):
    got = owners.tab.get((klass, mid), OWNER_UNKNOWN)
    if got != OWNER_UNKNOWN:
        return got
    owner = boot.method_owner(klass, rubycall.rid(mid))
    # Kept alive: a recycled class VALUE would otherwise read as a hit.
    gcroots.register_class(klass)
    owners.tab[(klass, mid)] = owner
    return owner


def owner_of(klass, mid):
    """The module klass resolves mid through; CRuby answers, iclasses count."""
    got = _owner_of(klass, mid, registry.version)
    if got == OWNER_UNKNOWN:
        got = _fill_owner(klass, mid)
    return got


RESPONDS_UNKNOWN = -2
RESPONDS_RECV = -1


@elidable
def _responds(klass, sym, version):
    return owners.rtab.get((klass, sym), RESPONDS_UNKNOWN)


@dont_look_inside
def _fill_responds(klass, sym):
    got = owners.rtab.get((klass, sym), RESPONDS_UNKNOWN)
    if got != RESPONDS_UNKNOWN:
        return got
    got = boot.responds(klass, sym)
    gcroots.register_class(klass)
    owners.rtab[(klass, sym)] = got
    return got


def responds(klass, sym):
    """respond_to? from the class alone, or RESPONDS_RECV when per-receiver."""
    got = _responds(klass, sym, registry.version)
    if got == RESPONDS_UNKNOWN:
        got = _fill_responds(klass, sym)
    return got


class _SymNames(object):
    def __init__(self):
        self.tab = {}       # Symbol VALUE -> its frozen String VALUE


sym_names = _SymNames()


@elidable
def _sym_name(sym, version):
    return sym_names.tab.get(sym, 0)


@dont_look_inside
def _fill_sym_name(sym):
    got = sym_names.tab.get(sym, 0)
    if got != 0:
        return got
    v = boot.sym_name(sym)
    # Held, not registered as a class: it is a String, in no frame.
    gcroots.hold(v)
    sym_names.tab[sym] = v
    return v


def sym_name(sym):
    """One frozen String per symbol for the process, so it is only filled."""
    got = _sym_name(sym, registry.version)
    if got == 0:
        got = _fill_sym_name(sym)
    return got


@elidable
def _kind_of(klass, target, version):
    return owners.ktab.get((klass, target), RESPONDS_UNKNOWN)


@dont_look_inside
def _fill_kind_of(klass, target):
    got = owners.ktab.get((klass, target), RESPONDS_UNKNOWN)
    if got != RESPONDS_UNKNOWN:
        return got
    got = boot.class_le(klass, target)
    gcroots.register_class(klass)
    gcroots.register_class(target)
    owners.ktab[(klass, target)] = got
    return got


def kind_of(klass, target):
    """kind_of? from the two classes; include or prepend clears the table."""
    got = _kind_of(klass, target, registry.version)
    if got == RESPONDS_UNKNOWN:
        got = _fill_kind_of(klass, target)
    return got


class _StructSlots(object):
    def __init__(self):
        self.tab = {}


struct_slots = _StructSlots()


@elidable
def _struct_index(klass, mid, version):
    return struct_slots.tab.get((klass, mid), IV_UNKNOWN)


@dont_look_inside
def _fill_struct_index(klass, mid):
    got = struct_slots.tab.get((klass, mid), IV_UNKNOWN)
    if got != IV_UNKNOWN:
        return got
    name = symbols.name_of(mid)
    if name.endswith('='):
        name = name[:-1]
    got = boot.struct_member_index(klass, boot.intern(name))
    struct_slots.tab[(klass, mid)] = got
    return got


def struct_member_index(klass, mid):
    """A Struct-generated reader/writer's slot, or -1 for another method."""
    got = _struct_index(klass, mid, registry.version)
    if got == IV_UNKNOWN:
        got = _fill_struct_index(klass, mid)
    return got


@elidable
def _super_owner(klass, owner, mid, version):
    return owners.stab.get((klass, owner, mid), OWNER_UNKNOWN)


@dont_look_inside
def _fill_super_owner(klass, owner, mid):
    got = owners.stab.get((klass, owner, mid), OWNER_UNKNOWN)
    if got != OWNER_UNKNOWN:
        return got
    found = boot.super_owner(klass, owner, rubycall.rid(mid))
    gcroots.register_class(klass)
    owners.stab[(klass, owner, mid)] = found
    return found


def super_owner(klass, owner, mid):
    """Where `super` from owner's mid lands; CRuby counts the iclasses."""
    got = _super_owner(klass, owner, mid, registry.version)
    if got == OWNER_UNKNOWN:
        got = _fill_super_owner(klass, owner, mid)
    return got


class _Slots(object):
    def __init__(self):
        self.tab = {}       # (shape_id, CRuby ID) -> slot, -1 absent, -2 bail


slots = _Slots()

IV_UNKNOWN = -3


@elidable
def iv_slot(shape_id, rid):
    """Elidable: a shape never changes; a new ivar means a new shape_id."""
    key = (shape_id, rid)
    got = slots.tab.get(key, IV_UNKNOWN)
    if got == IV_UNKNOWN:
        got = boot.shape_iv_index(shape_id, rid)
        slots.tab[key] = got
    return got


# Imported at the bottom: trampoline's own bottom import needs owner_of,
# defined above, so caches must finish loading before trampoline does.
from rpyyarv.dispatch.trampoline import flush_trampoline_cache
