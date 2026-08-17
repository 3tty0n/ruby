"""Lookup is elidable in (klass, mid, version) and a send promotes class_of(recv), so dispatch folds to one guard_value."""

from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import gcroots
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RubyException, UnsupportedOperation
from rpyyarv.rlib import (elidable, dont_look_inside, intmask, promote, r_uint,
                  raw_word, set_raw_word)

# Cycle guard: a superclass chain longer than this is a corrupt map.
MAX_ANCESTORS = 64


class Version(object):
    pass


KIND_ISEQ = 0
KIND_ATTR_READER = 1
KIND_ATTR_WRITER = 2
KIND_BMETHOD = 3


class MethodEntry(object):
    _immutable_fields_ = ['w_iseq', 'private', 'owner', 'mid', 'cref',
                          'kind', 'ivar', 'lexical', 'w_block']

    def __init__(self, w_iseq, private, owner=0, mid=0, cref=0,
                 kind=KIND_ISEQ, ivar=0, lexical=None, w_block=None):
        self.w_iseq = w_iseq
        self.kind = kind
        # For an accessor kind, the rpyyarv symbol id of the `@name` it reads.
        self.ivar = ivar
        # Class the body's constants resolve against; not owner, since `def self.x` lands on the singleton class.
        self.cref = cref
        # The interp.Cref chain the def was written in, for lexical constants.
        self.lexical = lexical
        # Toplevel defs land on Object as private: only an fcall may reach one.
        self.private = private
        # invokesuper resumes the lookup above (owner, mid).
        self.owner = owner
        self.mid = mid
        # KIND_BMETHOD only: the define_method block run as the method body.
        self.w_block = w_block


# Never reaches a caller of lookup: it only says the owner table has no answer yet.
OWNER_PENDING = MethodEntry(None, False)


class Registry(object):
    # Quasi-immutable: reads fold into the trace and definemethod invalidates.
    _immutable_fields_ = ['version?', 'module_owned?']

    def __init__(self):
        self.methods = {}       # klass VALUE -> {mid: MethodEntry}
        self.supers = {}        # klass VALUE -> superclass VALUE
        # Modules RPyYARV defined; they are never in supers, which only holds a walkable superclass chain.
        self.modules = {}
        self.version = Version()
        # Set once RPyYARV defines a module, which is the only way an entry can sit outside registry.supers; until then _lookup skips the owner detour entirely.
        self.module_owned = False


registry = Registry()


class _Trampoline(object):
    def __init__(self):
        self.enabled = False


trampoline = _Trampoline()


def enable_trampolines():
    """Off during the prelude: its Integer#times and Array#each must not replace CRuby's for CRuby's own callers."""
    trampoline.enabled = True


@dont_look_inside
def _install_trampoline(klass, mid, private):
    """A CRuby entry beside the registry one; it binds nothing and resolves through lookup, so redefine/undef needs no revisit."""
    if not trampoline.enabled:
        return
    boot.define_method_entry(klass, rubycall.rid(mid), private)


def _table_for(klass):
    table = registry.methods.get(klass, None)
    if table is None:
        table = {}
        registry.methods[klass] = table
    return table


def define(klass, mid, w_iseq, private, cref=0, lexical=None):
    _table_for(klass)[mid] = MethodEntry(w_iseq, private, klass, mid, cref,
                                         KIND_ISEQ, 0, lexical)
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_owners()
    _install_trampoline(klass, mid, private)


def define_attr(klass, mid, ivar, kind):
    """No trampoline: CRuby's own attr entry is still there, so a call from C reaches it directly."""
    _table_for(klass)[mid] = MethodEntry(None, False, klass, mid, 0, kind,
                                         ivar)
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_owners()


def define_bmethod(klass, mid, w_block, private):
    """No trampoline either: CRuby's own send already installed a real bmethod for mid, which reflection/super/respond_to? and any C caller still reach directly."""
    _table_for(klass)[mid] = MethodEntry(None, private, klass, mid, 0,
                                         KIND_BMETHOD, 0, None, w_block)
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_owners()
    gcroots.register_bmethod(w_block)


@dont_look_inside
def define_singleton(obj, mid, w_iseq, cref=0, lexical=None):
    """definesmethod targets the receiver's singleton class, always public (vm_insnhelper.c:6034)."""
    klass = boot.singleton_class(obj)
    if klass == 0 or value.is_immediate(klass):
        raise UnsupportedOperation(
            "'%s' cannot be given a singleton method" % value.repr_of(obj))
    if klass not in registry.supers:
        _record_ancestry(klass)
    define(klass, mid, w_iseq, False, cref, lexical)


@dont_look_inside
def _record_ancestry(klass):
    """Copy CRuby's chain above klass into the map so lookup stays in RPython; singleton classes reach the map only here."""
    k = klass
    n = 0
    while k != 0 and not value.is_immediate(k) and n < MAX_ANCESTORS:
        if k in registry.supers:
            return
        parent = boot.class_superclass(k)
        if parent == 0 or value.is_immediate(parent):
            return
        record_class(k, parent)
        k = parent
        n += 1


@dont_look_inside
def lookup_from_cruby(klass, mid):
    """CRuby already resolved, so the module it owns mid through names the entry; the walk below is the fallback for a klass the owner table cannot answer for, and skips iclasses."""
    entry = own_lookup(owner_of(klass, mid), mid)
    if entry is not None:
        return entry
    k = klass
    n = 0
    while k != 0 and not value.is_immediate(k) and n < MAX_ANCESTORS:
        entry = own_lookup(k, mid)
        if entry is not None:
            return entry
        k = boot.class_superclass(k)
        n += 1
    return None


# Direct-mapped cache of the trampoline's (rid, receiver class) -> (mid, entry); that pair is monomorphic in practice, so a hit skips rubycall.mid_of_rid, owner_of and own_lookup entirely.
_TC_SIZE = 512
_TC_MASK = _TC_SIZE - 1
_tc_rids = [0] * _TC_SIZE
_tc_klasses = [0] * _TC_SIZE     # 0 marks a slot empty: VALUE 0 is never a class
_tc_mids = [0] * _TC_SIZE
_tc_entries = [None] * _TC_SIZE


def flush_trampoline_cache():
    """Called wherever a lookup this cache could have memoised might change."""
    i = 0
    while i < _TC_SIZE:
        _tc_klasses[i] = 0
        i += 1


@dont_look_inside
def lookup_from_trampoline(rid, klass):
    """trampoline_callback's entry point: mid and its MethodEntry for a CRuby-resolved (rid, klass), cached by rid xor klass."""
    idx = intmask(rid * 1000003 ^ klass) & _TC_MASK
    if _tc_klasses[idx] == klass and _tc_rids[idx] == rid:
        return _tc_mids[idx], _tc_entries[idx]
    mid = rubycall.mid_of_rid(rid)
    entry = lookup_from_cruby(klass, mid) if mid != rubycall.NO_MID else None
    _tc_rids[idx] = rid
    _tc_klasses[idx] = klass
    _tc_mids[idx] = mid
    _tc_entries[idx] = entry
    return mid, entry


def undefine(klass, mid):
    """Drops the registry entry, so a later lookup falls through to CRuby's."""
    table = registry.methods.get(klass, None)
    if table is None or mid not in table:
        return False
    del table[mid]
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_owners()
    return True


def own_lookup(klass, mid):
    table = registry.methods.get(klass, None)
    if table is None:
        return None
    return table.get(mid, None)


def record_class(klass, superklass):
    registry.supers[klass] = superklass
    registry.version = Version()
    flush_trampoline_cache()
    gcroots.register_class(klass)


@elidable
def _is_known_class(klass, version):
    return klass in registry.supers


def is_known_class(klass):
    """Elidable on the method version, so a promoted klass folds the dict lookup out of the trace."""
    return _is_known_class(klass, registry.version)


@elidable
def _is_known_module(mod, version):
    return mod in registry.modules


def is_known_module(mod):
    """A module RPyYARV's own `module` body made; is_known_class cannot answer, since a module has no superclass to record."""
    return _is_known_module(mod, registry.version)


def _walk(klass, mid):
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


def _module_lookup(klass, mid):
    """registry.supers holds Class#superclass, which skips every iclass, so a module RPyYARV defined is invisible to _walk; CRuby's own owner names it."""
    owner = owners.tab.get((klass, mid), OWNER_UNKNOWN)
    if owner == OWNER_UNKNOWN:
        return OWNER_PENDING
    if owner == value.Q_NIL:
        return None
    table = registry.methods.get(owner, None)
    if table is None:
        return None
    return table.get(mid, None)


@elidable
def _lookup(klass, mid, version):
    """The walk and the owner check in one elidable, so a trace records one call_pure where two shifted its inlining."""
    entry = _walk(klass, mid)
    if entry is None:
        if not registry.module_owned:
            return None
        return _module_lookup(klass, mid)
    owner = owners.tab.get((klass, mid), OWNER_UNKNOWN)
    if owner == OWNER_UNKNOWN:
        return OWNER_PENDING
    if owner != entry.owner and owner != value.Q_NIL:
        # A module included behind supers' back shadows what the walk found; the owner's own table has the real entry, if it is ours.
        table = registry.methods.get(owner, None)
        if table is None:
            return None
        return table.get(mid, None)
    return entry


def lookup(klass, mid):
    """registry.supers holds Class#superclass, which skips iclasses, so a module could own mid and the walk above never see it; CRuby knows and every registry entry has a CRuby entry beside it."""
    entry = _lookup(klass, mid, registry.version)
    if entry is OWNER_PENDING:
        _fill_owner(klass, mid)
        entry = _lookup(klass, mid, registry.version)
    return entry


@elidable
def _own_lookup(klass, mid, version):
    table = registry.methods.get(klass, None)
    if table is None:
        return None
    return table.get(mid, None)


def lookup_owned(klass, mid):
    """own_lookup, but elidable on the method version, so a trace folds it away."""
    return _own_lookup(klass, mid, registry.version)


@elidable
def _lookup_core(klass, mid, version):
    """No Object fallback, so a toplevel `def +` does not read as a redefinition of Integer#+."""
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
    return None


def lookup_core(klass, mid):
    return _lookup_core(klass, mid, registry.version)


@dont_look_inside
def _reopened(cbase, rid):
    """Reopening e.g. Integer via rb_define_class_id_under with Object as super would be a superclass mismatch. cbase's own table only, as vm_const_get_under does: rb_const_get inherits, so `class Compiler; class Binding; end; end` would reopen ::Binding instead of making a nested class."""
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
    # A singleton method inherited from Foo is found only once meta(Bar) -> meta(Foo) is in the map.
    _record_ancestry(boot.singleton_class(klass))
    return klass


@dont_look_inside
def define_module(cbase, mid):
    """No entry in registry.supers: a module has no superclass to walk, and nothing is ever an instance of one."""
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
def alloc(klass):
    # The unprotected shim call: every caller checked is_known_class first.
    return boot.obj_alloc_fast(klass)


class ConstEntry(object):
    # A box, not the bare VALUE: Qfalse is 0, so no VALUE is free to stand for "not cached".
    _immutable_fields_ = ['value']

    def __init__(self, v):
        self.value = v


class SiteEntry(object):
    """What one opt_getconstant_path site resolved, and the cbase it resolved against."""
    _immutable_fields_ = ['base', 'value']

    def __init__(self, base, v):
        self.base = base
        self.value = v


# A second cbase at one site parks it here for good; no cbase VALUE is 0, so the guard can never match again.
SITE_POLY = SiteEntry(0, 0)


class ConstSite(object):
    """One inline cache slot per opt_getconstant_path operand; the site is green, so its entry folds into the trace."""
    def __init__(self):
        self.entry = None


class _Consts(object):
    # Quasi-immutable: a constant can be reassigned or removed, so every write replaces the tag and drops the traces that folded it.
    _immutable_fields_ = ['version?']

    def __init__(self):
        self.tab = {}       # (cbase VALUE, mid) -> ConstEntry
        # The same, for a cbase's own table alone; Qundef records a miss.
        self.attab = {}
        self.rooted = {}    # cbase VALUEs already handed to gcroots
        self.sites = []     # every ConstSite the loader built
        self.version = Version()


consts = _Consts()


def new_const_site():
    site = ConstSite()
    consts.sites.append(site)
    return site


def invalidate_consts():
    """CRuby's rb_clear_constant_cache_for_id, by way of the shim's const hook."""
    consts.tab = {}
    consts.attab = {}
    sites = consts.sites
    i = 0
    while i < len(sites):
        sites[i].entry = None
        i += 1
    consts.version = Version()


@elidable
def const_site(site, version):
    """Both arguments are green in a trace, so the entry and the VALUE it holds fold to literals."""
    return site.entry


@dont_look_inside
def const_site_fill(site, base, v):
    entry = site.entry
    if entry is None:
        root_base(base)
        site.entry = SiteEntry(base, v)
    elif entry is not SITE_POLY:
        site.entry = SITE_POLY
    else:
        return
    consts.version = Version()


def root_base(v):
    if v not in consts.rooted:
        # Kept alive: cbase roots the const table the cached VALUE still lives in, and a recycled class VALUE would otherwise read as a hit.
        consts.rooted[v] = None
        gcroots.register_class(v)


@elidable
def _const_cached(klass, mid, version):
    return consts.tab.get((klass, mid), None)


def const_get(klass, mid):
    entry = _const_cached(klass, mid, consts.version)
    if entry is None:
        entry = _const_fill(klass, mid)
    return entry.value


@elidable
def _const_at_cached(klass, mid, version):
    return consts.attab.get((klass, mid), None)


def const_at(klass, mid):
    """rb_const_lookup: what klass's own table holds, Qundef when it holds nothing."""
    entry = _const_at_cached(klass, mid, consts.version)
    if entry is None:
        entry = _const_at_fill(klass, mid)
    return entry.value


@dont_look_inside
def _const_at_fill(klass, mid):
    entry = ConstEntry(boot.const_at(klass, rubycall.const_rid(mid)))
    root_base(klass)
    consts.attab[(klass, mid)] = entry
    consts.version = Version()
    return entry


@dont_look_inside
def _const_fill(klass, mid):
    entry = ConstEntry(boot.const_get(klass, rubycall.const_rid(mid)))
    root_base(klass)
    consts.tab[(klass, mid)] = entry
    consts.version = Version()
    return entry


@dont_look_inside
def const_set(klass, mid, v):
    boot.const_set(klass, rubycall.rid(mid), v)


class _Owners(object):
    # Tagged by registry.version, not one of its own: a lookup reads both, and one quasi-immutable is one guard_not_invalidated.
    def __init__(self):
        self.tab = {}       # (klass VALUE, mid) -> owning module VALUE
        self.stab = {}      # the same, for the module above that one
        self.rtab = {}      # (klass VALUE, Symbol VALUE) -> respond_to? for every instance
        self.ktab = {}      # (klass VALUE, module VALUE) -> kind_of? for every instance
        self.invalidations = 0


owners = _Owners()

OWNER_UNKNOWN = -1


def invalidate_owners():
    """CRuby's rb_clear_method_cache, by way of the shim's method hook: every def, undef, alias, include and prepend reaches it."""
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


@dont_look_inside
def _fill_owner(klass, mid):
    owner = boot.method_owner(klass, rubycall.rid(mid))
    # Kept alive: a recycled class VALUE would otherwise read as a hit, and the owner is in the registered class's ancestry.
    gcroots.register_class(klass)
    owners.tab[(klass, mid)] = owner
    registry.version = Version()
    flush_trampoline_cache()


def owner_of(klass, mid):
    """The module klass resolves mid through; asked of CRuby, so modules included behind our back count."""
    got = _owner_of(klass, mid, registry.version)
    if got == OWNER_UNKNOWN:
        _fill_owner(klass, mid)
        got = _owner_of(klass, mid, registry.version)
    return got


RESPONDS_UNKNOWN = -2
RESPONDS_RECV = -1


@elidable
def _responds(klass, sym, version):
    return owners.rtab.get((klass, sym), RESPONDS_UNKNOWN)


@dont_look_inside
def _fill_responds(klass, sym):
    got = boot.responds(klass, sym)
    gcroots.register_class(klass)
    owners.rtab[(klass, sym)] = got
    registry.version = Version()
    flush_trampoline_cache()


def responds(klass, sym):
    """respond_to? answered from the class alone, or RESPONDS_RECV when an overridden respond_to?/respond_to_missing? makes it a per-receiver question."""
    got = _responds(klass, sym, registry.version)
    if got == RESPONDS_UNKNOWN:
        _fill_responds(klass, sym)
        got = _responds(klass, sym, registry.version)
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
    v = boot.sym_name(sym)
    # Held, not registered as a class: it is a String, and no frame covers this table.
    gcroots.hold(v)
    sym_names.tab[sym] = v
    registry.version = Version()
    flush_trampoline_cache()


def sym_name(sym):
    """The String Symbol#name returns; one per symbol for the life of the process, so the entry is only ever filled."""
    got = _sym_name(sym, registry.version)
    if got == 0:
        _fill_sym_name(sym)
        got = _sym_name(sym, registry.version)
    return got


@elidable
def _kind_of(klass, target, version):
    return owners.ktab.get((klass, target), RESPONDS_UNKNOWN)


@dont_look_inside
def _fill_kind_of(klass, target):
    got = boot.class_le(klass, target)
    gcroots.register_class(klass)
    gcroots.register_class(target)
    owners.ktab[(klass, target)] = got
    registry.version = Version()
    flush_trampoline_cache()


def kind_of(klass, target):
    """kind_of? answered from the two classes; every instance of klass gives the same answer, and an include or prepend clears the table."""
    got = _kind_of(klass, target, registry.version)
    if got == RESPONDS_UNKNOWN:
        _fill_kind_of(klass, target)
        got = _kind_of(klass, target, registry.version)
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
    name = symbols.name_of(mid)
    if name.endswith('='):
        name = name[:-1]
    struct_slots.tab[(klass, mid)] = \
        boot.struct_member_index(klass, boot.intern(name))


def struct_member_index(klass, mid):
    """A Struct-generated reader/writer's slot, or -1 for another method."""
    got = _struct_index(klass, mid, registry.version)
    if got == IV_UNKNOWN:
        _fill_struct_index(klass, mid)
        got = _struct_index(klass, mid, registry.version)
    return got


@elidable
def _super_owner(klass, owner, mid, version):
    return owners.stab.get((klass, owner, mid), OWNER_UNKNOWN)


@dont_look_inside
def _fill_super_owner(klass, owner, mid):
    found = boot.super_owner(klass, owner, rubycall.rid(mid))
    gcroots.register_class(klass)
    owners.stab[(klass, owner, mid)] = found
    registry.version = Version()
    flush_trampoline_cache()


def super_owner(klass, owner, mid):
    """Where `super` from owner's mid lands, along klass's chain; CRuby answers, so the iclasses registry.supers skips still count."""
    got = _super_owner(klass, owner, mid, registry.version)
    if got == OWNER_UNKNOWN:
        _fill_super_owner(klass, owner, mid)
        got = _super_owner(klass, owner, mid, registry.version)
    return got


def owns_identity(klass, mid):
    """True when klass resolves mid to BasicObject's, which is a pointer compare."""
    return owner_of(klass, mid) == value.core_class(value.C_BASIC_OBJECT)


class _Slots(object):
    def __init__(self):
        self.tab = {}       # (shape_id, CRuby ID) -> slot, -1 absent, -2 bail


slots = _Slots()

IV_UNKNOWN = -3


@elidable
def iv_slot(shape_id, rid):
    """Elidable: a shape node never changes, and gaining an ivar moves the object to a different shape_id, this cache's key."""
    key = (shape_id, rid)
    got = slots.tab.get(key, IV_UNKNOWN)
    if got == IV_UNKNOWN:
        got = boot.shape_iv_index(shape_id, rid)
        slots.tab[key] = got
    return got


def _data_fields(obj, flags):
    """The imemo/fields a typed T_DATA keeps its ivars in, which internal/imemo.h gives the RObject layout; 0 for anything else, including the shareable receivers ivar_ractor_check (variable.c:1220) may raise for."""
    if (flags & value.T_MASK) == value.T_DATA \
            and (flags & (value.FL_TYPED_DATA | value.FL_SHAREABLE)) \
            == value.FL_TYPED_DATA:
        return raw_word(obj, value.FIELDS_WORD)
    return 0


def ivar_get(obj, mid):
    """T_OBJECT reads compile to a shape guard plus a raw field load, and a typed T_DATA to the same over its fields object."""
    if obj != 0 and (obj & value.IMMEDIATE_MASK) == 0:
        flags = raw_word(obj, value.FLAGS_WORD)
        kind = flags & value.T_MASK
        if kind == value.T_CLASS or kind == value.T_MODULE:
            got = boot.class_ivar_get(obj, rubycall.const_rid(mid))
            if got != value.Q_UNDEF:
                return got
        fields = obj
        # One promoted word, so the three tests below fold into its one guard.
        hdr = promote(flags & value.IV_HEADER_MASK)
        if (hdr & value.T_MASK) != value.T_OBJECT:
            fields = _data_fields(obj, flags)
            if fields != 0:
                hdr = promote(raw_word(fields, value.FLAGS_WORD)
                              & value.IV_HEADER_MASK)
        if fields != 0:
            shape_id = (hdr >> value.SHAPE_SHIFT) & value.SHAPE_MASK
            slot = iv_slot(shape_id, rubycall.const_rid(mid))
            if slot >= 0:
                if hdr & value.ROBJECT_HEAP:
                    return raw_word(raw_word(fields, value.FIELDS_WORD), slot)
                return raw_word(fields, value.FIELDS_WORD + slot)
            if slot == -1:
                return value.Q_NIL
    return _ivar_get_slow(obj, mid)


@dont_look_inside
def _ivar_get_slow(obj, mid):
    return boot.ivar_get(obj, rubycall.rid(mid))


class _Barrier(object):
    # Quasi-immutable: install() writes it once, before any Ruby code runs.
    _immutable_fields_ = ['direct?']

    def __init__(self):
        self.direct = False


barrier = _Barrier()


class TransEntry(object):
    _immutable_fields_ = ['after', 'slot']

    def __init__(self, after, slot):
        self.after = after
        self.slot = slot


class _Trans(object):
    # Quasi-immutable: a shape edge does not exist until the first object takes it, so recording one drops the traces that folded its absence.
    _immutable_fields_ = ['version?']

    def __init__(self):
        self.tab = {}       # (shape_id, CRuby ID) -> TransEntry
        self.version = Version()


trans = _Trans()


@elidable
def _iv_transition(shape_id, rid, version):
    return trans.tab.get((shape_id, rid), None)


def ivar_set(obj, mid, v):
    """Raw store: an immediate needs no write barrier (ruby/internal/gc.h:788), a heap value takes CRuby's; frozen or missing slot falls back."""
    if obj != 0 and (obj & value.IMMEDIATE_MASK) == 0:
        immediate = value.is_immediate(v)
        if immediate or barrier.direct:
            flags = raw_word(obj, value.FLAGS_WORD)
            # One promoted word, so the four tests below fold into its one guard.
            hdr = promote(flags & value.IV_SET_HEADER_MASK)
            if (hdr & value.FL_FREEZE) == 0:
                # Only an object holding its own fields may gain one here: a separate imemo/fields may have to be reallocated and hung back off its owner.
                own = (hdr & value.T_MASK) == value.T_OBJECT
                fields = obj
                if not own:
                    fields = _data_fields(obj, flags)
                    if fields != 0:
                        flags = raw_word(fields, value.FLAGS_WORD)
                        hdr = promote(flags & value.IV_SET_HEADER_MASK)
                if fields != 0:
                    shape_id = (hdr >> value.SHAPE_SHIFT) & value.SHAPE_MASK
                    rid = rubycall.const_rid(mid)
                    slot = iv_slot(shape_id, rid)
                    after = shape_id
                    if slot == -1 and own:
                        entry = _iv_transition(shape_id, rid, trans.version)
                        if entry is not None:
                            after = entry.after
                            slot = entry.slot
                    if slot >= 0:
                        if hdr & value.ROBJECT_HEAP:
                            set_raw_word(raw_word(fields, value.FIELDS_WORD),
                                         slot, v)
                        else:
                            set_raw_word(fields, value.FIELDS_WORD + slot, v)
                        if after != shape_id:
                            # The field is stored first: nothing can collect between two raw stores, and the new shape would expose the slot before it holds a VALUE.
                            set_raw_word(obj, value.FLAGS_WORD,
                                         intmask((r_uint(flags)
                                                  & r_uint(value.SHAPE_FLAG_MASK))
                                                 | (r_uint(after)
                                                    << value.SHAPE_SHIFT)))
                        if not immediate:
                            boot.obj_written(fields, v)
                        return
                    if slot == -1 and own:
                        _ivar_add_slow(obj, shape_id, rid, v)
                        return
    _ivar_set_slow(obj, mid, v)


@dont_look_inside
def _ivar_add_slow(obj, before, rid, v):
    """The first store of an ivar transitions the shape, which may allocate, so CRuby has to do it; the edge it creates is permanent, so the next object takes it in RPython."""
    boot.ivar_set(obj, rid, v)
    if (before, rid) in trans.tab:
        return
    after = (raw_word(obj, value.FLAGS_WORD)
             >> value.SHAPE_SHIFT) & value.SHAPE_MASK
    slot = boot.shape_add_ivar_slot(before, after, rid)
    if slot < 0:
        return
    trans.tab[(before, rid)] = TransEntry(after, slot)
    trans.version = Version()


@dont_look_inside
def _ivar_set_slow(obj, mid, v):
    boot.ivar_set(obj, rubycall.rid(mid), v)


def check_object_layout():
    """The ivar fast path reads RObject by hand and writes its shape id back; refuse a CRuby it misreads."""
    got = boot.object_layout()
    want = [value.SHAPE_SHIFT, value.SHAPE_ID_BITS, value.ROBJECT_HEAP,
            value.FIELDS_WORD, value.T_MASK, value.T_OBJECT,
            value.FL_FREEZE, value.SHAPE_ID_IN_FLAGS, value.T_DATA,
            value.FL_TYPED_DATA, value.FIELDS_WORD, value.FL_SHAREABLE]
    return got == want


def install():
    value.install_classes(boot.core_classes())
    barrier.direct = boot.wb_direct()
    boot.set_const_hook(invalidate_consts)
    boot.set_method_hook(invalidate_owners)
