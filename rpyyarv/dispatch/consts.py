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
    def __init__(self):
        self.entry = None


class _Consts(object):
    # Quasi-immutable: a write replaces the tag, dropping traces that folded it.
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
    """CRuby's rb_clear_constant_cache_for_id, via the shim's const hook."""
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
    """Both arguments are green, so the entry folds to a literal."""
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
        # Kept alive: a recycled class VALUE would otherwise read as a hit.
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
    """rb_const_lookup: klass's own table, Qundef when it holds nothing."""
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
