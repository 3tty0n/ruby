"""The one door from RPython into CRuby's method dispatch."""

import boot
import symbols
import value
from rlib import dont_look_inside, elidable


class _State(object):
    def __init__(self):
        self.rids = {}      # rpyyarv symbol id -> CRuby ID


state = _State()


class _Stress(object):
    # Quasi-immutable, so the check folds away but entry_point's write to a
    # prebuilt instance still invalidates it. See value._Classes.
    _immutable_fields_ = ['flag?']

    def __init__(self):
        self.flag = False


stress = _Stress()


@dont_look_inside
def rid(mid):
    if mid in state.rids:
        return state.rids[mid]
    r = boot.intern(symbols.name_of(mid))
    state.rids[mid] = r
    return r


@dont_look_inside
def call(recv, mid, args):
    return boot.funcallv(recv, rid(mid), args, symbols.name_of(mid))


@dont_look_inside
def call1(recv, mid, arg):
    return boot.funcallv(recv, rid(mid), [arg], symbols.name_of(mid))


@dont_look_inside
def call0(recv, mid):
    return boot.funcallv(recv, rid(mid), [], symbols.name_of(mid))


@dont_look_inside
def call2(recv, mid, a, b):
    return boot.funcallv(recv, rid(mid), [a, b], symbols.name_of(mid))


@dont_look_inside
def call_with_block(recv, mid, args, handle):
    return boot.call_with_block(recv, rid(mid), args, handle,
                                symbols.name_of(mid))


@dont_look_inside
def ary_resurrect(ary):
    return boot.ary_resurrect(ary)


@dont_look_inside
def ary_store(ary, idx, val):
    # A call, not a raw store: rb_ary_store runs the write barrier.
    boot.ary_store(ary, idx, val)


@dont_look_inside
def ary_new(values):
    return boot.ary_new(values)


@dont_look_inside
def hash_new(capa):
    return boot.hash_new(capa)


@dont_look_inside
def hash_aset(h, key, val):
    return boot.hash_aset(h, key, val)


@dont_look_inside
def hash_resurrect(h):
    return boot.hash_resurrect(h)


@dont_look_inside
def splat_array(ary, flag):
    return boot.splat_array(ary, 1 if flag else 0)


@dont_look_inside
def range_new(low, high, excl):
    return boot.range_new(low, high, excl)


@dont_look_inside
def gvar_get(mid):
    return boot.gvar_get(symbols.name_of(mid))


@dont_look_inside
def gvar_set(mid, v):
    boot.gvar_set(symbols.name_of(mid), v)


@dont_look_inside
def swap_errinfo(v):
    return boot.swap_errinfo(v)


@dont_look_inside
def to_bignum(n):
    return boot.int2inum(n)


@dont_look_inside
def is_string(v):
    return not value.is_immediate(v) and boot.is_string(v)


@elidable
def const_rid(mid):
    """rid for a mid the trace already knows: folds to a constant."""
    return rid(mid)


@dont_look_inside
def _gc_start():
    boot.gc_start()


def gc_stress_point():
    """RPYYARV_GC_STRESS=1: a full GC at every dispatch."""
    if stress.flag:
        _gc_start()
