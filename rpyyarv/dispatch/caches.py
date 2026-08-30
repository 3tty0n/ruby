"""Elidable lookup caches: owner, respond_to?, kind_of?, struct, ivar slot."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import gcroots
from rpyyarv import symbols
from rpyyarv import rubycall
from rpyyarv.rlib import elidable, dont_look_inside
from rpyyarv.dispatch.core import (lookup, registry, MethodEntry, Version,
                                   bump_name, name_version)


class _Owners(object):
    # Tagged by registry.version: one quasi-immutable, one guard.
    def __init__(self):
        self.tab = {}       # (klass VALUE, mid) -> owning module VALUE
        self.stab = {}      # the same, for the module above that one
        self.rtab = {}  # (klass VALUE, Symbol VALUE) -> respond_to? per inst
        self.ktab = {}  # (klass VALUE, module VALUE) -> kind_of? per instance
        # Which cached answers name each mid, so a def drops those and
        # leaves every other name's answers standing.
        self.by_mid = {}    # mid -> [klass, ...] keys held in tab
        self.by_sup = {}    # mid -> [(klass, owner), ...] keys held in stab
        self.by_sym = {}    # respond_to? Symbol -> [klass, ...] keys in rtab
        # lookup's own answer, so a repeat send skips the ancestor walk.
        self.res = {}       # klass VALUE -> {mid: MethodEntry}
        self.res_by_mid = {}   # mid -> [klass, ...] keys held in res
        # The same for lookup_core, which every core operator asks first.
        self.cres = {}
        self.cres_by_mid = {}
        self.invalidations = 0
        self.skipped = 0


owners = _Owners()


class _OwnHook(object):
    """Depth of our own trampoline installs, which CRuby reports back to us."""
    def __init__(self):
        self.depth = 0
        # The name being installed; only a report for it is ours to skip.
        self.rid = 0


own_hook = _OwnHook()


def method_state_changed(klass, rid):
    """CRuby cleared its method cache. If our own def caused it, the precise
    invalidate_for has already run; anything else is someone else's change.
    A method_added hook can define or include under us, so only a report that
    names what we are installing may be skipped."""
    own_rid = boot.as_signed(rid)
    if own_hook.depth > 0 and own_rid != 0 and own_rid == own_hook.rid:
        owners.skipped += 1
        return
    debug.count_invalidation(boot.as_signed(klass), own_rid)
    _drop_redefined(boot.as_signed(klass), own_rid)
    mid = rubycall.mid_of_rid(own_rid) if own_rid != 0 else rubycall.NO_MID
    if mid == rubycall.NO_MID:
        invalidate_owners()
    else:
        invalidate_for(mid)


@dont_look_inside
def _drop_redefined(klass, rid):
    """CRuby redefined rid on klass behind us, so our entry describes a method
    that no longer exists; drop it and let lookup fall through to CRuby's."""
    if rid == 0:
        return
    table = registry.methods.get(klass, None)
    if table is None:
        return
    mid = rubycall.mid_of_rid(rid)
    if mid != rubycall.NO_MID and mid in table:
        del table[mid]


OWNER_UNKNOWN = -1


def _note_key(index, name, klass):
    """Which classes hold a cached answer for this name."""
    if name in index:
        index[name].append(klass)
    else:
        index[name] = [klass]


# A walk that has not run yet, and one that ran and found nothing.
LOOKUP_PENDING = MethodEntry(None, False)
LOOKUP_MISS = MethodEntry(None, False)


@elidable
def resolved(klass, mid, version, nversion):
    """The cached answer, LOOKUP_PENDING when the walk still owes one."""
    table = owners.res.get(klass, None)
    if table is None:
        return LOOKUP_PENDING
    return table.get(mid, LOOKUP_PENDING)


@dont_look_inside
def keep_resolved(klass, mid, entry):
    table = owners.res.get(klass, None)
    if table is None:
        table = {}
        owners.res[klass] = table
        gcroots.register_class(klass)
    table[mid] = LOOKUP_MISS if entry is None else entry
    _note_key(owners.res_by_mid, mid, klass)


@elidable
def core_resolved(klass, mid, version, nversion):
    table = owners.cres.get(klass, None)
    if table is None:
        return LOOKUP_PENDING
    return table.get(mid, LOOKUP_PENDING)


@dont_look_inside
def keep_core(klass, mid, entry):
    table = owners.cres.get(klass, None)
    if table is None:
        table = {}
        owners.cres[klass] = table
        gcroots.register_class(klass)
    table[mid] = LOOKUP_MISS if entry is None else entry
    _note_key(owners.cres_by_mid, mid, klass)


def site_lookup(site, klass, mid):
    """lookup(), but a repeat send from the same site is two compares.
    Off-trace only: inside one the lookup folds into the class guard."""
    if site.ic_klass == klass and site.ic_version is registry.version \
            and site.ic_name is name_version(mid):
        got = site.ic_entry
        return None if got is LOOKUP_MISS else got
    entry = lookup(klass, mid)
    # Registered by keep_resolved, so the class cannot die under the cache.
    site.ic_entry = LOOKUP_MISS if entry is None else entry
    site.ic_klass = klass
    site.ic_version = registry.version
    site.ic_name = name_version(mid)
    return entry


def invalidate_for(mid):
    """A def of mid stales only answers naming mid; drop exactly those.
    kind_of? does not depend on methods, so ktab is never touched here."""
    owners.skipped += 1
    res = owners.res_by_mid.get(mid, None)
    if res is not None:
        for klass in res:
            table = owners.res.get(klass, None)
            if table is not None and mid in table:
                del table[mid]
        del owners.res_by_mid[mid]
    cres = owners.cres_by_mid.get(mid, None)
    if cres is not None:
        for klass in cres:
            table = owners.cres.get(klass, None)
            if table is not None and mid in table:
                del table[mid]
        del owners.cres_by_mid[mid]
    klasses = owners.by_mid.get(mid, None)
    if klasses is not None:
        for klass in klasses:
            if (klass, mid) in owners.tab:
                del owners.tab[(klass, mid)]
            if (klass, mid) in struct_slots.tab:
                del struct_slots.tab[(klass, mid)]
        del owners.by_mid[mid]
    pairs = owners.by_sup.get(mid, None)
    if pairs is not None:
        for klass, owner in pairs:
            if (klass, owner, mid) in owners.stab:
                del owners.stab[(klass, owner, mid)]
        del owners.by_sup[mid]
    sym = rubycall.sym_value(mid)
    syms = owners.by_sym.get(sym, None)
    if syms is not None:
        for klass in syms:
            if (klass, sym) in owners.rtab:
                del owners.rtab[(klass, sym)]
        del owners.by_sym[sym]
        # respond_to? answers hang off the global version, not the name's.
        registry.version = Version()
    bump_name(mid)
    flush_trampoline_cache()


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
    owners.res = {}
    owners.res_by_mid = {}
    owners.cres = {}
    owners.cres_by_mid = {}
    owners.by_mid = {}
    owners.by_sup = {}
    owners.by_sym = {}
    registry.version = Version()
    flush_trampoline_cache()


@elidable
def _owner_of(klass, mid, version, nversion):
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
    _note_key(owners.by_mid, mid, klass)
    return owner


def owner_of(klass, mid):
    """The module klass resolves mid through; CRuby answers, iclasses count."""
    got = _owner_of(klass, mid, registry.version, name_version(mid))
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
    _note_key(owners.by_sym, sym, klass)
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
def _struct_index(klass, mid, version, nversion):
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
    _note_key(owners.by_mid, mid, klass)
    return got


def struct_member_index(klass, mid):
    """A Struct-generated reader/writer's slot, or -1 for another method."""
    got = _struct_index(klass, mid, registry.version, name_version(mid))
    if got == IV_UNKNOWN:
        got = _fill_struct_index(klass, mid)
    return got


@elidable
def _super_owner(klass, owner, mid, version, nversion):
    return owners.stab.get((klass, owner, mid), OWNER_UNKNOWN)


@dont_look_inside
def _fill_super_owner(klass, owner, mid):
    got = owners.stab.get((klass, owner, mid), OWNER_UNKNOWN)
    if got != OWNER_UNKNOWN:
        return got
    found = boot.super_owner(klass, owner, rubycall.rid(mid))
    gcroots.register_class(klass)
    owners.stab[(klass, owner, mid)] = found
    if mid in owners.by_sup:
        owners.by_sup[mid].append((klass, owner))
    else:
        owners.by_sup[mid] = [(klass, owner)]
    return found


def super_owner(klass, owner, mid):
    """Where `super` from owner's mid lands; CRuby counts the iclasses."""
    got = _super_owner(klass, owner, mid, registry.version,
                       name_version(mid))
    if got == OWNER_UNKNOWN:
        got = _fill_super_owner(klass, owner, mid)
    return got


class _StructArity(object):
    def __init__(self):
        self.tab = {}       # class VALUE -> member count, -1 when not a Struct


struct_arities = _StructArity()

STRUCT_UNKNOWN = -2


@elidable
def _struct_arity(klass, version):
    return struct_arities.tab.get(klass, STRUCT_UNKNOWN)


@dont_look_inside
def _fill_struct_arity(klass):
    got = struct_arities.tab.get(klass, STRUCT_UNKNOWN)
    if got != STRUCT_UNKNOWN:
        return got
    got = boot.struct_arity(klass)
    gcroots.register_class(klass)
    struct_arities.tab[klass] = got
    return got


def struct_arity(klass):
    """Members of a positional Struct class; -1 for anything else."""
    got = _struct_arity(klass, registry.version)
    if got == STRUCT_UNKNOWN:
        got = _fill_struct_arity(klass)
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
