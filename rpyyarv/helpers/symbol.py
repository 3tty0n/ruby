"""Symbol fast paths."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import value
from rpyyarv.helpers.core import *
from rpyyarv.helpers.core import _core_op, _cruby_owns, _owned_by_core, _sym_op


def sym_name(recv):
    """Symbol#name: one frozen String per symbol (symbol.c), cached once."""
    if (recv & value.SYMBOL_MASK) != value.SYMBOL_FLAG:
        return value.Q_UNDEF
    if not _core_op(value.C_SYMBOL, B_SYM_NAME, NAME):
        return value.Q_UNDEF
    return dispatch.sym_name(recv)


def _sym_eq(a, mid):
    """Symbol#== is rb_obj_equal (string.c:12227); one VALUE per name."""
    if value.class_of(a) != value.core_class(value.C_SYMBOL):
        return False
    if not _sym_op(B_SYM_EQ):
        return False
    if mid == NEQ:
        return dispatch.owns_identity(value.core_class(value.C_SYMBOL), NEQ)
    return True


def sym_eqq(a, b):
    """Symbol#=== is Kernel's ==, which for a Symbol compares the words."""
    if value.class_of(a) != value.core_class(value.C_SYMBOL):
        return value.Q_UNDEF
    if not _cruby_owns(B_KERNEL_EQQ) or not _sym_op(B_SYM_EQ):
        return value.Q_UNDEF
    if dispatch.lookup_core(value.core_class(value.C_SYMBOL), EQQ) is not None:
        return value.Q_UNDEF
    return value.newbool(a == b)


def sym_to_s(recv):
    if not boot.is_symbol(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_SYMBOL, TO_S):
        return value.Q_UNDEF
    return boot.sym_to_s(recv)
