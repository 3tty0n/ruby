"""CRuby-side bridge: trampoline installation and lookup from C."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import value
from rpyyarv import rubycall
from rpyyarv.rlib import dont_look_inside, intmask
from rpyyarv.dispatch.core import (registry, record_class, own_lookup,
                                   MAX_ANCESTORS, MethodEntry, KIND_BMETHOD)


class _Trampoline(object):
    def __init__(self):
        self.enabled = False


trampoline = _Trampoline()


def enable_trampolines():
    """Off during the prelude: its methods must not replace CRuby's own."""
    trampoline.enabled = True


@dont_look_inside
def _install_trampoline(klass, mid, visibility, entry):
    """A CRuby entry beside the registry one; it resolves through lookup."""
    if not trampoline.enabled:
        return
    key = boot.define_method_entry(klass, rubycall.rid(mid), visibility)
    # Copies of the entry (alias, define_method(Method)) share this def.
    if key != 0:
        registry.defs[key] = entry


@dont_look_inside
def _record_ancestry(klass):
    """Copy CRuby's chain above klass into the map; lookup stays in RPython."""
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
    """CRuby resolved, so its owner names the entry; the walk is fallback."""
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


# Direct-mapped (rid, class) -> (mid, entry) cache; monomorphic in practice.
_TC_SIZE = 512
_TC_MASK = _TC_SIZE - 1
_tc_rids = [0] * _TC_SIZE
_tc_klasses = [0] * _TC_SIZE    # 0 marks a slot empty: VALUE 0 is never a class
_tc_mids = [0] * _TC_SIZE
_tc_entries = [None] * _TC_SIZE


def flush_trampoline_cache():
    """Called wherever a lookup this cache could have memoised might change."""
    i = 0
    while i < _TC_SIZE:
        _tc_klasses[i] = 0
        i += 1


_bmethod_idents = {}


@dont_look_inside
def bmethod_identity(owner, mid, w_block):
    """A cached KIND_BMETHOD entry naming (owner, mid), for frame identity."""
    key = (owner, mid)
    entry = _bmethod_idents.get(key, None)
    if entry is None or entry.w_block is not w_block:
        entry = MethodEntry(None, False, owner, mid, 0, KIND_BMETHOD, 0,
                            None, w_block)
        _bmethod_idents[key] = entry
    return entry


@dont_look_inside
def lookup_from_def(key):
    """The entry a CRuby method-def address stands for; exact identity."""
    return registry.defs.get(key, None)


@dont_look_inside
def lookup_from_trampoline(rid, klass):
    """trampoline_callback's entry point, cached by rid xor klass."""
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


# Imported at the bottom: caches imports trampoline, so this edge can only
# be bound once caches has already defined owner_of.
from rpyyarv.dispatch.caches import owner_of
