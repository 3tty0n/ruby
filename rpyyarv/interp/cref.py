"""Lexical scope chain (CREF)."""
from __future__ import absolute_import

from rpyyarv import dispatch
from rpyyarv import value

class Cref(object):
    """Lexical scope chained as CRuby's rb_cref_t; klass 0 is Object."""
    _immutable_fields_ = ['klass', 'outer', 'by_eval', 'const_base']

    def __init__(self, klass, outer, by_eval=False):
        self.klass = klass
        self.outer = outer
        # CREF_PUSHED_BY_EVAL: a def lands here, but const lookup steps over it.
        self.by_eval = by_eval
        self.native = 0
        # Resolved once: _const_base is on every constant read's hot path.
        if by_eval and outer is not None:
            self.const_base = outer.const_base
        else:
            self.const_base = klass
        # klass -> Cref: a re-run class body reuses the node const guards hold.
        self.inner = {}
        self.eval_inner = {}


TOP_CREF = Cref(0, None)


def _push_cref(outer, klass, by_eval=False):
    table = outer.eval_inner if by_eval else outer.inner
    node = table.get(klass, None)
    if node is None:
        dispatch.root_base(klass)
        node = Cref(klass, outer, by_eval)
        table[klass] = node
    return node


def _cref_of(frame):
    """Const-resolution scope chain; a method frame uses its entry's."""
    c = frame.cref
    if c is None:
        entry = frame.entry
        if entry is not None:
            c = entry.lexical
    if c is None:
        return TOP_CREF
    return c


def _cref_klass(cref):
    # const_base, not klass: an instance_eval scope names no constants.
    if cref.const_base == 0:
        return value.core_class(value.C_OBJECT)
    return cref.const_base
