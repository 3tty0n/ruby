"""Version counters and the method table: define, undefine, lookup."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import gcroots
from rpyyarv import value
from rpyyarv.error import UnsupportedOperation
from rpyyarv.rlib import elidable, dont_look_inside, we_are_jitted


# Cycle guard: a superclass chain longer than this is a corrupt map.
MAX_ANCESTORS = 64


class Version(object):
    pass


KIND_ISEQ = 0
KIND_ATTR_READER = 1
KIND_ATTR_WRITER = 2
KIND_BMETHOD = 3
# undef_method's poison: blocks the ancestor lookup a delete lets through.
KIND_UNDEF = 4


class MethodEntry(object):
    _immutable_fields_ = ['w_iseq', 'private', 'prot', 'owner', 'mid', 'cref',
                          'kind', 'ivar', 'lexical', 'w_block']

    def __init__(self, w_iseq, private, owner=0, mid=0, cref=0,
                 kind=KIND_ISEQ, ivar=0, lexical=None, w_block=None,
                 prot=False):
        self.w_iseq = w_iseq
        self.kind = kind
        # For an accessor kind, the rpyyarv symbol id of the `@name` it reads.
        self.ivar = ivar
        # Constants resolve here, not owner: def self.x is on the singleton.
        self.cref = cref
        # The interp.Cref chain the def was written in, for lexical constants.
        self.lexical = lexical
        # Toplevel defs land on Object as private: only an fcall may reach one.
        self.private = private
        # protected: an explicit receiver is fine while the caller is kin.
        self.prot = prot
        # invokesuper resumes the lookup above (owner, mid).
        self.owner = owner
        self.mid = mid
        # KIND_BMETHOD only: the define_method block run as the method body.
        self.w_block = w_block


# Never reaches a caller of lookup: the owner table has no answer yet.
OWNER_PENDING = MethodEntry(None, False)


class Registry(object):
    # Quasi-immutable: reads fold into the trace and definemethod invalidates.
    _immutable_fields_ = ['version?', 'module_owned?']

    def __init__(self):
        self.methods = {}       # klass VALUE -> {mid: MethodEntry}
        self.defs = {}          # CRuby method-def address -> MethodEntry
        self.supers = {}        # klass VALUE -> superclass VALUE
        # Modules RPyYARV defined; never in supers, which holds only classes.
        self.modules = {}
        self.version = Version()
        # Set when a module is defined; else _lookup skips the owner detour.
        self.module_owned = False


registry = Registry()


def _table_for(klass):
    table = registry.methods.get(klass, None)
    if table is None:
        table = {}
        registry.methods[klass] = table
    return table


def define(klass, mid, w_iseq, private, cref=0, lexical=None,
           orig_mid=0, orig_owner=0, prot=False):
    # An alias keeps its source's mid and owner, so super resumes as CRuby's.
    entry = MethodEntry(w_iseq, private,
                        orig_owner if orig_owner != 0 else klass,
                        orig_mid if orig_mid != 0 else mid,
                        cref, KIND_ISEQ, 0, lexical, None, prot)
    _table_for(klass)[mid] = entry
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_for(mid)
    _install_trampoline(klass, mid, 2 if prot else (1 if private else 0),
                        entry)


def define_attr(klass, mid, ivar, kind, private=False, prot=False):
    """No trampoline: CRuby's own attr entry still answers a call from C."""
    _table_for(klass)[mid] = MethodEntry(None, private, klass, mid, 0, kind,
                                         ivar, None, None, prot)
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_for(mid)


def define_bmethod(klass, mid, w_block, private, prot=False):
    """No trampoline: CRuby's send already installed a bmethod for mid."""
    _table_for(klass)[mid] = MethodEntry(None, private, klass, mid, 0,
                                         KIND_BMETHOD, 0, None, w_block, prot)
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_for(mid)
    gcroots.register_bmethod(w_block)


@dont_look_inside
def define_singleton(obj, mid, w_iseq, cref=0, lexical=None):
    """definesmethod targets the singleton, public (vm_insnhelper.c:6034)."""
    klass = boot.singleton_class(obj)
    if klass == 0 or value.is_immediate(klass):
        raise UnsupportedOperation(
            "'%s' cannot be given a singleton method" % value.repr_of(obj))
    if klass not in registry.supers:
        _record_ancestry(klass)
    define(klass, mid, w_iseq, False, cref, lexical)


@dont_look_inside
def define_singleton_bmethod(obj, mid, w_block):
    """As define_singleton for KIND_BMETHOD; module_function needs both."""
    klass = boot.singleton_class(obj)
    if klass == 0 or value.is_immediate(klass):
        raise UnsupportedOperation(
            "'%s' cannot be given a singleton method" % value.repr_of(obj))
    if klass not in registry.supers:
        _record_ancestry(klass)
    define_bmethod(klass, mid, w_block, False)


def undefine(klass, mid):
    """Drops the registry entry, so a later lookup falls through to CRuby's."""
    table = registry.methods.get(klass, None)
    if table is None or mid not in table:
        return False
    del table[mid]
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_for(mid)
    return True


def undef_method(klass, mid):
    """Module#undef_method leaves a poison entry, so ancestors are blocked."""
    _table_for(klass)[mid] = MethodEntry(None, False, klass, mid, 0, KIND_UNDEF)
    registry.version = Version()
    flush_trampoline_cache()
    invalidate_for(mid)


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
    """Elidable on the method version, so a promoted klass folds it away."""
    return _is_known_class(klass, registry.version)


@elidable
def _is_known_module(mod, version):
    return mod in registry.modules


def is_known_module(mod):
    """A module RPyYARV made; is_known_class cannot: modules have no super."""
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
                # Poison blocks the ancestors too, as CRuby's undef does.
                return None if entry.kind == KIND_UNDEF else entry
        k = supers.get(k, 0)
        n += 1
    # Toplevel defs live on Object; reachable from any receiver, as in Ruby.
    table = methods.get(value.core_class(value.C_OBJECT), None)
    if table is not None:
        entry = table.get(mid, None)
        return None if entry is not None and entry.kind == KIND_UNDEF else entry
    return None


def _module_lookup(klass, mid):
    """supers skips iclasses, so an RPyYARV module is invisible to _walk."""
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
    """Walk and owner check in one elidable: one call_pure, not two."""
    entry = _walk(klass, mid)
    if entry is None:
        if not registry.module_owned:
            return None
        return _module_lookup(klass, mid)
    owner = owners.tab.get((klass, mid), OWNER_UNKNOWN)
    if owner == OWNER_UNKNOWN:
        return OWNER_PENDING
    if owner != entry.owner and owner != value.Q_NIL:
        # A module included behind supers' back shadows the walk's find.
        table = registry.methods.get(owner, None)
        if table is None:
            return None
        return table.get(mid, None)
    return entry


@dont_look_inside
def _lookup_filled(klass, mid):
    """Opaque on purpose: a trace must not reuse the pending answer."""
    return _lookup(klass, mid, registry.version)


def lookup(klass, mid):
    """supers skips iclasses, so CRuby is asked who owns mid."""
    # Only off-trace: a trace folds _lookup away, and a fill recorded into
    # one would stay in it as a dict store on every later run.
    jitted = we_are_jitted()
    if not jitted:
        got = resolved(klass, mid, registry.version)
        if got is not LOOKUP_PENDING:
            return None if got is LOOKUP_MISS else got
    entry = _lookup(klass, mid, registry.version)
    if entry is OWNER_PENDING:
        _fill_owner(klass, mid)
        entry = _lookup_filled(klass, mid)
        if entry is OWNER_PENDING:
            return None
    if not jitted:
        keep_resolved(klass, mid, entry)
    return entry


@elidable
def _own_lookup(klass, mid, version):
    table = registry.methods.get(klass, None)
    if table is None:
        return None
    return table.get(mid, None)


def lookup_owned(klass, mid):
    """own_lookup, but elidable on the method version."""
    return _own_lookup(klass, mid, registry.version)


@elidable
def _lookup_core(klass, mid, version):
    """No Object fallback, so a toplevel `def +` is no Integer#+ redefine."""
    methods = registry.methods
    supers = registry.supers
    k = klass
    n = 0
    while k != 0 and n < MAX_ANCESTORS:
        table = methods.get(k, None)
        if table is not None:
            entry = table.get(mid, None)
            if entry is not None:
                return None if entry.kind == KIND_UNDEF else entry
        k = supers.get(k, 0)
        n += 1
    return None


def lookup_core(klass, mid):
    return _lookup_core(klass, mid, registry.version)


def owns_identity(klass, mid):
    """True when klass resolves mid to BasicObject's, a pointer compare."""
    return owner_of(klass, mid) == value.core_class(value.C_BASIC_OBJECT)


# Imported at the bottom: caches imports core, so this edge can only be
# bound once core's own definitions exist.
from rpyyarv.dispatch.caches import (LOOKUP_MISS, LOOKUP_PENDING, keep_resolved,
                                     resolved,
                                     invalidate_for, invalidate_owners, owner_of, owners,
                                     _fill_owner, OWNER_UNKNOWN)
from rpyyarv.dispatch.trampoline import (flush_trampoline_cache,
                                         _install_trampoline, _record_ancestry)
