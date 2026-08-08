"""Lookup is elidable in (klass, mid, version) and a send promotes class_of(recv), so dispatch folds to one guard_value."""

import boot
import gcroots
import rubycall
import value
from error import RubyException, UnsupportedOperation
from rlib import (elidable, dont_look_inside, promote, raw_word,
                  set_raw_word)

# Cycle guard: a superclass chain longer than this is a corrupt map.
MAX_ANCESTORS = 64


class Version(object):
    pass


KIND_ISEQ = 0
KIND_ATTR_READER = 1
KIND_ATTR_WRITER = 2


class MethodEntry(object):
    _immutable_fields_ = ['w_iseq', 'private', 'owner', 'mid', 'cref',
                          'kind', 'ivar']

    def __init__(self, w_iseq, private, owner=0, mid=0, cref=0,
                 kind=KIND_ISEQ, ivar=0):
        self.w_iseq = w_iseq
        self.kind = kind
        # For an accessor kind, the rpyyarv symbol id of the `@name` it reads.
        self.ivar = ivar
        # Class the body's constants resolve against; not owner, since `def self.x` lands on the singleton class.
        self.cref = cref
        # Toplevel defs land on Object as private: only an fcall may reach one.
        self.private = private
        # invokesuper resumes the lookup above (owner, mid).
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


def define(klass, mid, w_iseq, private, cref=0):
    _table_for(klass)[mid] = MethodEntry(w_iseq, private, klass, mid, cref)
    registry.version = Version()
    invalidate_owners()
    _install_trampoline(klass, mid, private)


def define_attr(klass, mid, ivar, kind):
    """No trampoline: CRuby's own attr entry is still there, so a call from C reaches it directly."""
    _table_for(klass)[mid] = MethodEntry(None, False, klass, mid, 0, kind,
                                         ivar)
    registry.version = Version()
    invalidate_owners()


@dont_look_inside
def define_singleton(obj, mid, w_iseq, cref=0):
    """definesmethod targets the receiver's singleton class, always public (vm_insnhelper.c:6034)."""
    klass = boot.singleton_class(obj)
    if klass == 0 or value.is_immediate(klass):
        raise UnsupportedOperation(
            "'%s' cannot be given a singleton method" % value.repr_of(obj))
    if klass not in registry.supers:
        _record_ancestry(klass)
    define(klass, mid, w_iseq, False, cref)


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
    """Walks CRuby's own chain, since a CRuby-only class is absent from the map; no Object fallback, CRuby already resolved."""
    k = klass
    n = 0
    while k != 0 and not value.is_immediate(k) and n < MAX_ANCESTORS:
        entry = own_lookup(k, mid)
        if entry is not None:
            return entry
        k = boot.class_superclass(k)
        n += 1
    return None


def undefine(klass, mid):
    """Drops the registry entry, so a later lookup falls through to CRuby's."""
    table = registry.methods.get(klass, None)
    if table is None or mid not in table:
        return False
    del table[mid]
    registry.version = Version()
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


@elidable
def _lookup_super(owner, mid, version):
    """Starts above owner; no Object fallback, or super would find an unrelated toplevel def."""
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
def _reopened(cbase, rid):
    """Reopening e.g. Integer via rb_define_class_id_under with Object as super would be a superclass mismatch."""
    try:
        v = boot.const_get(cbase, rid)
    except RubyException:
        return 0
    if value.is_immediate(v) or not boot.is_class(v):
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
def alloc(klass):
    return boot.obj_alloc(klass)


def const_get(klass, mid):
    # const_rid outside the residual call, so the trace folds it to a literal.
    return _const_get(klass, rubycall.const_rid(mid))


@dont_look_inside
def _const_get(klass, rid):
    return boot.const_get(klass, rid)


@dont_look_inside
def const_set(klass, mid, v):
    boot.const_set(klass, rubycall.rid(mid), v)


class _Owners(object):
    # Quasi-immutable: a method owner can change, so every write replaces the tag and drops the traces that folded it.
    _immutable_fields_ = ['version?']

    def __init__(self):
        self.tab = {}       # (klass VALUE, mid) -> 1 identity, 0 not
        self.version = Version()


owners = _Owners()

OWNER_UNKNOWN = -1


def invalidate_owners():
    owners.tab = {}
    owners.version = Version()


@elidable
def _owns_identity(klass, mid, version):
    return owners.tab.get((klass, mid), OWNER_UNKNOWN)


@dont_look_inside
def _fill_identity(klass, mid):
    owner = boot.method_owner(klass, rubycall.rid(mid))
    got = 1 if owner == value.core_class(value.C_BASIC_OBJECT) else 0
    # Kept alive: a recycled class VALUE would otherwise read as a hit.
    gcroots.register_class(klass)
    owners.tab[(klass, mid)] = got
    owners.version = Version()


def owns_identity(klass, mid):
    """True when klass resolves mid to BasicObject's (a pointer compare); asked of CRuby, so modules included behind our back count."""
    got = _owns_identity(klass, mid, owners.version)
    if got == OWNER_UNKNOWN:
        _fill_identity(klass, mid)
        got = _owns_identity(klass, mid, owners.version)
    return got == 1


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


def ivar_get(obj, mid):
    """T_OBJECT reads compile to a shape guard plus a raw field load."""
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


class _Barrier(object):
    # Quasi-immutable: install() writes it once, before any Ruby code runs.
    _immutable_fields_ = ['direct?']

    def __init__(self):
        self.direct = False


barrier = _Barrier()


def ivar_set(obj, mid, v):
    """Raw store: an immediate needs no write barrier (ruby/internal/gc.h:788), a heap value takes CRuby's; frozen or missing slot falls back."""
    if obj != 0 and (obj & value.IMMEDIATE_MASK) == 0:
        immediate = value.is_immediate(v)
        if immediate or barrier.direct:
            flags = raw_word(obj, value.FLAGS_WORD)
            if (flags & value.T_MASK) == value.T_OBJECT \
                    and (flags & value.FL_FREEZE) == 0:
                shape_id = promote(
                    (flags >> value.SHAPE_SHIFT) & value.SHAPE_MASK)
                slot = iv_slot(shape_id, rubycall.const_rid(mid))
                if slot >= 0:
                    if flags & value.ROBJECT_HEAP:
                        set_raw_word(raw_word(obj, value.FIELDS_WORD), slot, v)
                    else:
                        set_raw_word(obj, value.FIELDS_WORD + slot, v)
                    if not immediate:
                        boot.obj_written(obj, v)
                    return
    _ivar_set_slow(obj, mid, v)


@dont_look_inside
def _ivar_set_slow(obj, mid, v):
    boot.ivar_set(obj, rubycall.rid(mid), v)


def check_object_layout():
    """The ivar fast path reads RObject by hand; refuse a CRuby it misreads."""
    got = boot.object_layout()
    want = [value.SHAPE_SHIFT, value.SHAPE_ID_BITS, value.ROBJECT_HEAP,
            value.FIELDS_WORD, value.T_MASK, value.T_OBJECT,
            value.FL_FREEZE]
    return got == want


def install():
    value.install_classes(boot.core_classes())
    barrier.direct = boot.wb_direct()
