"""Constant caches: opt_getconstant_path sites and Module#const_get."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import gcroots
from rpyyarv import rubycall
from rpyyarv.rlib import elidable, dont_look_inside
from rpyyarv.dispatch.core import Version


class ConstEntry(object):
    # A box, not the VALUE: Qfalse is 0, so none is free for "not cached".
    _immutable_fields_ = ['value']

    def __init__(self, v):
        self.value = v


class SiteEntry(object):
    """What one opt_getconstant_path site resolved, and its cbase."""
    _immutable_fields_ = ['base', 'value']

    def __init__(self, base, v):
        self.base = base
        self.value = v


# A second cbase parks the site here: no cbase is 0, so the guard never hits.
SITE_POLY = SiteEntry(0, 0)


class ConstSite(object):
    """One inline cache slot per opt_getconstant_path operand; it is green."""
    # Quasi-immutable: a refill drops the traces that folded this site alone.
    _immutable_fields_ = ['entry?']

    def __init__(self):
        self.entry = None


class _Consts(object):
    def __init__(self):
        self.tab = {}       # (cbase VALUE, mid) -> ConstEntry
        # The same, for a cbase's own table alone; Qundef records a miss.
        self.attab = {}
        # Qualified A::B: rb_public_const_get_from, so Object is not a hit.
        self.ftab = {}
        self.rooted = {}    # cbase VALUEs already handed to gcroots
        self.by_name = {}   # mid -> the ConstSites whose path names it


consts = _Consts()


# One quasi-immutable per bucket of constant names, so a const_set of one
# name drops only the traces that folded a name in its bucket.
# ponytail: buckets, not one cell per name; widen if collisions show up.
CONST_BUCKETS = 1024


class _ConstCell(object):
    _immutable_fields_ = ['version?']

    def __init__(self):
        self.version = Version()


class _ConstNames(object):
    _immutable_fields_ = ['cells[*]']

    def __init__(self):
        self.cells = [_ConstCell() for _ in range(CONST_BUCKETS)]


const_names = _ConstNames()


def const_name_version(mid):
    """The version a lookup of mid depends on; folds, mid being green."""
    return const_names.cells[mid & (CONST_BUCKETS - 1)].version


def new_const_site(path):
    site = ConstSite()
    i = 0
    while i < len(path):
        mid = path[i]
        sites = consts.by_name.get(mid, None)
        if sites is None:
            sites = []
            consts.by_name[mid] = sites
        sites.append(site)
        i += 1
    return site


class _Invalidations(object):
    """Named constant invalidations, and the ones no cache of ours held."""

    def __init__(self):
        self.count = 0
        self.skipped = 0


const_invalidations = _Invalidations()


def _drop_named(tab, mid):
    dead = []
    for key in tab:
        if key[1] == mid:
            dead.append(key)
    i = 0
    while i < len(dead):
        del tab[dead[i]]
        i += 1


def invalidate_consts(rid):
    """CRuby's rb_clear_constant_cache_for_id, via the shim's const hook."""
    mid = rubycall.mid_of_rid(boot.as_signed(rid))
    if mid == rubycall.NO_MID:
        # A name no lookup of ours ever interned: nothing caches it.
        const_invalidations.skipped += 1
        return
    _drop_named(consts.tab, mid)
    _drop_named(consts.attab, mid)
    _drop_named(consts.ftab, mid)
    sites = consts.by_name.get(mid, None)
    if sites is not None:
        i = 0
        while i < len(sites):
            # Guarded: a same-value write still kills every folding trace.
            if sites[i].entry is not None:
                sites[i].entry = None
            i += 1
    const_names.cells[mid & (CONST_BUCKETS - 1)].version = Version()
    const_invalidations.count += 1


def const_site(site):
    """A quasi-immutable read; site is green, so the entry folds."""
    return site.entry


@dont_look_inside
def const_site_fill(site, base, v):
    entry = site.entry
    if entry is None:
        root_base(base)
        site.entry = SiteEntry(base, v)
    elif entry is not SITE_POLY:
        site.entry = SITE_POLY


def root_base(v):
    if v not in consts.rooted:
        # Kept alive: a recycled class VALUE would otherwise read as a hit.
        consts.rooted[v] = None
        gcroots.register_class(v)


@elidable
def _const_cached(klass, mid, version):
    return consts.tab.get((klass, mid), None)


def const_get(klass, mid):
    entry = _const_cached(klass, mid, const_name_version(mid))
    if entry is None:
        entry = _const_fill(klass, mid)
    return entry.value


@elidable
def _const_from_cached(klass, mid, version):
    return consts.ftab.get((klass, mid), None)


def const_get_from(klass, mid):
    """A::B: CRuby stops at Object, so a toplevel name is not found here."""
    entry = _const_from_cached(klass, mid, const_name_version(mid))
    if entry is None:
        entry = _const_from_fill(klass, mid)
    return entry.value


@dont_look_inside
def _const_from_fill(klass, mid):
    entry = consts.ftab.get((klass, mid), None)
    if entry is not None:
        return entry
    entry = ConstEntry(boot.const_get_from(klass, rubycall.const_rid(mid)))
    root_base(klass)
    consts.ftab[(klass, mid)] = entry
    return entry


@elidable
def _const_at_cached(klass, mid, version):
    return consts.attab.get((klass, mid), None)


def const_at(klass, mid):
    """rb_const_lookup: klass's own table, Qundef when it holds nothing."""
    entry = _const_at_cached(klass, mid, const_name_version(mid))
    if entry is None:
        entry = _const_at_fill(klass, mid)
    return entry.value


# Filling never bumps the version: only rb_clear_constant_cache invalidates.
@dont_look_inside
def _const_at_fill(klass, mid):
    entry = consts.attab.get((klass, mid), None)
    if entry is not None:
        return entry
    entry = ConstEntry(boot.const_at(klass, rubycall.const_rid(mid)))
    root_base(klass)
    consts.attab[(klass, mid)] = entry
    return entry


@dont_look_inside
def _const_fill(klass, mid):
    entry = consts.tab.get((klass, mid), None)
    if entry is not None:
        return entry
    entry = ConstEntry(boot.const_get(klass, rubycall.const_rid(mid)))
    root_base(klass)
    consts.tab[(klass, mid)] = entry
    return entry


@dont_look_inside
def const_set(klass, mid, v):
    boot.const_set(klass, rubycall.rid(mid), v)
