"""Receiver-class-aware method dispatch: RPyYARV's inline cache.

Methods live in a (klass VALUE -> mid -> entry) registry alongside a
superclass map, and lookup is elidable in (klass, mid, version). A send
promotes class_of(recv), so the lookup compiles away behind one guard_value
on the receiver's class word, with a bridge per extra class.
"""

import boot
import gcroots
import rubycall
import value
from error import RubyException, UnsupportedOperation
from rlib import elidable, dont_look_inside, promote, raw_word

# Cycle guard: a superclass chain longer than this is a corrupt map.
MAX_ANCESTORS = 64


class Version(object):
    pass


class MethodEntry(object):
    _immutable_fields_ = ['w_iseq', 'private', 'owner', 'mid', 'cref']

    def __init__(self, w_iseq, private, owner=0, mid=0, cref=0):
        self.w_iseq = w_iseq
        # The class the `def` was written in, which a constant in the body
        # resolves against; not owner, since `def self.x` lands on the
        # singleton class but reads constants of the class itself.
        self.cref = cref
        # Toplevel defs land on Object as private: only an fcall may reach one.
        self.private = private
        # The class the def landed on, and under which name; invokesuper
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


class _Trampoline(object):
    def __init__(self):
        self.enabled = False


trampoline = _Trampoline()


def enable_trampolines():
    """Turned on after the prelude: its Integer#times and Array#each
    reimplement methods CRuby already has, and must not replace them for
    CRuby's own callers."""
    trampoline.enabled = True


@dont_look_inside
def _install_trampoline(klass, mid, private):
    """A CRuby method entry beside the registry one, so a core method calling
    back reaches the definition RPyYARV holds. Nothing is bound here: the
    entry resolves through lookup at call time, so a later redefinition or an
    undef needs no second visit."""
    if not trampoline.enabled:
        return
    boot.define_method_entry(klass, rubycall.rid(mid), private)


def define(klass, mid, w_iseq, private, cref=0):
    table = registry.methods.get(klass, None)
    if table is None:
        table = {}
        registry.methods[klass] = table
    table[mid] = MethodEntry(w_iseq, private, klass, mid, cref)
    registry.version = Version()
    _install_trampoline(klass, mid, private)


@dont_look_inside
def define_singleton(obj, mid, w_iseq, cref=0):
    """definesmethod: the target is the receiver's singleton class and the
    visibility is always public (vm_insnhelper.c:6034)."""
    klass = boot.singleton_class(obj)
    if klass == 0 or value.is_immediate(klass):
        raise UnsupportedOperation(
            "'%s' cannot be given a singleton method" % value.repr_of(obj))
    if klass not in registry.supers:
        _record_ancestry(klass)
    define(klass, mid, w_iseq, False, cref)


@dont_look_inside
def _record_ancestry(klass):
    """CRuby's superclass chain above klass, copied into the map so lookup
    walks it without leaving RPython. A singleton class is created by CRuby,
    never by define_class, so nothing else would put it there."""
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
    """lookup for a call that came in through the trampoline: walks CRuby's
    own superclass chain, since a class only CRuby created is absent from the
    registry's map. No Object fallback -- CRuby resolved the entry already."""
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
    """Drop a method RPyYARV defined, so a later lookup falls through to
    CRuby's."""
    table = registry.methods.get(klass, None)
    if table is None or mid not in table:
        return False
    del table[mid]
    registry.version = Version()
    return True


def own_lookup(klass, mid):
    """The entry defined on klass itself, which is what an alias copies."""
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
    """_lookup without the Object fallback, so a toplevel `def +` does not
    read as a redefinition of Integer#+."""
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
    """_lookup starting above owner. No Object fallback, or super would find
    an unrelated toplevel def."""
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
    """An existing class of that name, or 0: reopening Integer through
    rb_define_class_id_under with Object as super is a superclass mismatch."""
    try:
        v = boot.const_get(cbase, rid)
    except RubyException:
        return 0
    if value.is_immediate(v) or not boot.is_class(v):
        return 0
    return v


@dont_look_inside
def define_class(cbase, mid, super_v):
    """defineclass's class half: create or find it, then remember its parent."""
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
    # The metaclass chain beside it: class_of(Bar) is meta(Bar), so a
    # singleton method inherited from Foo is only found natively once
    # meta(Bar) -> meta(Foo) is in the map.
    _record_ancestry(boot.singleton_class(klass))
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
    """Which field slot a shape keeps an ivar in. Elidable because a shape
    node never changes: gaining an ivar moves the object to a different
    shape_id, this cache's key, so an entry goes unreachable, never stale."""
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


@dont_look_inside
def ivar_set(obj, mid, v):
    # Still a call: a raw store would skip CRuby's write barrier and leave an
    # old->young reference unremembered by RGenGC.
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
