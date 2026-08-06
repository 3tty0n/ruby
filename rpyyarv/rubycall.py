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
    # Quasi-immutable, not plain immutable: the rtyper would fold a prebuilt
    # instance's immutable field to its pre-boot value forever. With '?' the
    # JIT constant-folds the check and entry_point's write invalidates it.
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
    """RPYYARV_GC_STRESS=1: a full GC at every dispatch, to shake out
    VALUEs the mark hook cannot reach."""
    if stress.flag:
        _gc_start()
