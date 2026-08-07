"""The opt_* instructions: a fixnum or Array fast path that touches no rb_*
API, and value.Q_UNDEF for everything else.

Q_UNDEF is what vm_opt_plus and friends answer when their fast path does not
apply (vm_insnhelper.c:6880); interp.py then runs the send for real, so a
receiver whose class RPyYARV holds a method for reaches that method rather
than CRuby's. Each fast path is also gated on the operator still being the
one CRuby booted with, as BASIC_OP_UNREDEFINED_P gates its own.
"""

import boot
import dispatch
import rubycall
import symbols
import value
from rlib import ovfcheck

PLUS = symbols.intern('+')
MINUS = symbols.intern('-')
MULT = symbols.intern('*')
LT = symbols.intern('<')
GT = symbols.intern('>')
LE = symbols.intern('<=')
GE = symbols.intern('>=')
EQ = symbols.intern('==')
NEQ = symbols.intern('!=')
DIV = symbols.intern('/')
MOD = symbols.intern('%')
AREF = symbols.intern('[]')
ASET = symbols.intern('[]=')
LENGTH = symbols.intern('length')
SIZE = symbols.intern('size')
EMPTY_P = symbols.intern('empty?')
LTLT = symbols.intern('<<')
AND = symbols.intern('&')
OR = symbols.intern('|')

# One bit per (class, operator) pair, in the order boot_shim.c's
# rpyyarv_bop_mask sets them.
B_INT_PLUS = 0
B_INT_MINUS = 1
B_INT_MULT = 2
B_INT_DIV = 3
B_INT_MOD = 4
B_INT_EQ = 5
B_INT_LT = 6
B_INT_LE = 7
B_INT_GT = 8
B_INT_GE = 9
B_INT_AND = 10
B_INT_OR = 11
B_ARY_AREF = 12
B_ARY_ASET = 13
B_ARY_LENGTH = 14
B_ARY_SIZE = 15
B_ARY_EMPTY_P = 16
B_COUNT = 17

_INT_MID = [PLUS, MINUS, MULT, DIV, MOD, EQ, LT, LE, GT, GE, AND, OR]
_ARY_MID = [AREF, ASET, LENGTH, SIZE, EMPTY_P]


class _Bops(object):
    # Quasi-immutable: a fast path's guard folds into the trace, and
    # refresh() invalidates every trace that read it. See value._Classes for
    # why a prebuilt instance cannot use a plain immutable field.
    _immutable_fields_ = ['mask?']

    def __init__(self):
        # Every bit set until refresh() runs, so nothing takes a fast path
        # before CRuby has been asked.
        self.mask = -1


bops = _Bops()


def refresh():
    """Re-ask CRuby which of the watched operators it still owns. Called
    wherever RPyYARV can see the method world change; a redefinition made
    inside a CRuby call with no RPyYARV definition after it is still missed.
    """
    count, mask = boot.bop_mask()
    if count != B_COUNT:
        return False
    bops.mask = mask
    return True


def _cruby_owns(bit):
    return bops.mask & (1 << bit) == 0


def _int_op(bit):
    """CRuby still owns the Integer operator, and RPyYARV has not defined one
    of its own. The registry lookup is elidable on the method version, so it
    folds away and a later `class Integer` invalidates it."""
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_INTEGER),
                                     _INT_MID[bit]) is None)


def _ary_op(bit):
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_ARRAY),
                                     _ARY_MID[bit - B_ARY_AREF]) is None)


def _from_int(n):
    if value.fixable(n):
        return value.int2fix(n)
    return rubycall.to_bignum(n)


def _fix2(a, b, bit):
    return value.is_fixnum(a) and value.is_fixnum(b) and _int_op(bit)


def add(a, b):
    if _fix2(a, b, B_INT_PLUS):
        return _from_int(value.fix2int(a) + value.fix2int(b))
    return value.Q_UNDEF


def sub(a, b):
    if _fix2(a, b, B_INT_MINUS):
        return _from_int(value.fix2int(a) - value.fix2int(b))
    return value.Q_UNDEF


def mul(a, b):
    if _fix2(a, b, B_INT_MULT):
        try:
            return _from_int(ovfcheck(value.fix2int(a) * value.fix2int(b)))
        except OverflowError:
            pass
    return value.Q_UNDEF


def lt(a, b):
    if _fix2(a, b, B_INT_LT):
        return value.newbool(value.fix2int(a) < value.fix2int(b))
    return value.Q_UNDEF


def gt(a, b):
    if _fix2(a, b, B_INT_GT):
        return value.newbool(value.fix2int(a) > value.fix2int(b))
    return value.Q_UNDEF


def le(a, b):
    if _fix2(a, b, B_INT_LE):
        return value.newbool(value.fix2int(a) <= value.fix2int(b))
    return value.Q_UNDEF


def ge(a, b):
    if _fix2(a, b, B_INT_GE):
        return value.newbool(value.fix2int(a) >= value.fix2int(b))
    return value.Q_UNDEF


def eq(a, b):
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a == b)
    return value.Q_UNDEF


def neq(a, b):
    # BOP_NEQ is never flagged: vm_opt_neq resolves `!=` to BasicObject#!=
    # and then asks opt_equality, so Integer#== is the definition that counts.
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a != b)
    return value.Q_UNDEF


def and_(a, b):
    # The tag bits are the same in both operands, so they survive the mask.
    if _fix2(a, b, B_INT_AND):
        return a & b
    return value.Q_UNDEF


def or_(a, b):
    if _fix2(a, b, B_INT_OR):
        return a | b
    return value.Q_UNDEF


def _both_positive(a, b):
    # Ruby's / and % floor, RPython's truncate: only take operands where the
    # two agree.
    return (value.is_fixnum(a) and value.is_fixnum(b)
            and value.fix2int(a) >= 0 and value.fix2int(b) > 0)


def div(a, b):
    if _both_positive(a, b) and _int_op(B_INT_DIV):
        return value.int2fix(value.fix2int(a) // value.fix2int(b))
    return value.Q_UNDEF


def mod(a, b):
    if _both_positive(a, b) and _int_op(B_INT_MOD):
        return value.int2fix(value.fix2int(a) % value.fix2int(b))
    return value.Q_UNDEF


def aref(recv, idx):
    """Array[Fixnum] reads the elements in place."""
    if value.is_plain_array(recv) and value.is_fixnum(idx) \
            and _ary_op(B_ARY_AREF):
        i = value.fix2int(idx)
        n = value.ary_len(recv)
        if i < 0:
            i += n
        if i >= 0 and i < n:
            return value.ary_at(recv, i)
        return value.Q_NIL
    return value.Q_UNDEF


def aset(recv, idx, val):
    if value.is_plain_array(recv) and value.is_fixnum(idx) \
            and _ary_op(B_ARY_ASET):
        rubycall.ary_store(recv, value.fix2int(idx), val)
        return val
    return value.Q_UNDEF


def length(recv):
    if value.is_plain_array(recv) and _ary_op(B_ARY_LENGTH):
        return value.int2fix(value.ary_len(recv))
    return value.Q_UNDEF


def size(recv):
    if value.is_plain_array(recv) and _ary_op(B_ARY_SIZE):
        return value.int2fix(value.ary_len(recv))
    return value.Q_UNDEF


def empty_p(recv):
    if value.is_plain_array(recv) and _ary_op(B_ARY_EMPTY_P):
        return value.newbool(value.ary_len(recv) == 0)
    return value.Q_UNDEF


def opt_not(recv):
    # TODO: vm_opt_not asks whether `!` still resolves to rb_obj_not, which no
    # BOP flag records, so a redefined #! is still ignored here.
    return value.newbool(not value.is_true(recv))


def check_array_layout():
    """The Array fast paths read RArray by hand; refuse a CRuby they misread."""
    got = boot.array_layout()
    want = [value.ARY_EMBED_FLAG, value.ARY_EMBED_LEN_SHIFT,
            value.ARY_EMBED_LEN_MASK, value.ARY_HEAP_LEN_WORD,
            value.ARY_HEAP_PTR_WORD, value.ARY_EMBED_WORD]
    return got == want
