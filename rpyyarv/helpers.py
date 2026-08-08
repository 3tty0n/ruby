"""opt_* instructions: a fixnum/Array fast path touching no rb_* API, else value.Q_UNDEF as vm_opt_plus and friends do (vm_insnhelper.c:6880), so interp.py runs the real send."""

import math

import boot
import dispatch
import rubycall
import symbols
import value
from rlib import INFINITY, LONG_BIT, NAN, ovfcheck, promote

PLUS = symbols.intern('+')
MINUS = symbols.intern('-')
MULT = symbols.intern('*')
LT = symbols.intern('<')
GT = symbols.intern('>')
LE = symbols.intern('<=')
GE = symbols.intern('>=')
EQ = symbols.intern('==')
NEQ = symbols.intern('!=')
EQUAL_P = symbols.intern('equal?')
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
XOR = symbols.intern('^')
RSHIFT = symbols.intern('>>')
BEGIN = symbols.intern('begin')
END = symbols.intern('end')
EXCLUDE_END_P = symbols.intern('exclude_end?')
SQRT = symbols.intern('sqrt')

# One bit per (class, operator) pair, in the order boot_shim.c's rpyyarv_bop_mask sets them.
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
B_INT_XOR = 12
B_INT_RSHIFT = 13
B_ARY_AREF = 14
B_ARY_ASET = 15
B_ARY_LENGTH = 16
B_ARY_SIZE = 17
B_ARY_EMPTY_P = 18
B_SYM_EQ = 19
B_RNG_BEGIN = 20
B_RNG_END = 21
B_RNG_EXCL = 22
B_FLT_PLUS = 23
B_FLT_MINUS = 24
B_FLT_MULT = 25
B_FLT_DIV = 26
B_FLT_LT = 27
B_FLT_LE = 28
B_FLT_GT = 29
B_FLT_GE = 30
B_FLT_EQ = 31
B_MATH_SQRT = 32
B_COUNT = 33

_INT_MID = [PLUS, MINUS, MULT, DIV, MOD, EQ, LT, LE, GT, GE, AND, OR, XOR,
            RSHIFT]
_ARY_MID = [AREF, ASET, LENGTH, SIZE, EMPTY_P]
_SYM_MID = [EQ]
_FLT_MID = [PLUS, MINUS, MULT, DIV, LT, LE, GT, GE, EQ]
# The Integer bit the same operator takes when the *receiver* is the Fixnum.
_FLT_AS_INT = [B_INT_PLUS, B_INT_MINUS, B_INT_MULT, B_INT_DIV, B_INT_LT,
               B_INT_LE, B_INT_GT, B_INT_GE, B_INT_EQ]


class _Bops(object):
    # Quasi-immutable: a fast path's guard folds into the trace and refresh() invalidates it; see value._Classes for why not a plain immutable field.
    _immutable_fields_ = ['mask?']

    def __init__(self):
        # Every bit set until refresh() runs, so nothing takes a fast path before CRuby has been asked.
        self.mask = -1


bops = _Bops()


def refresh():
    """Re-ask CRuby which watched operators it still owns; a redefinition made inside a CRuby call with no RPyYARV definition after it is still missed."""
    dispatch.invalidate_owners()
    count, mask = boot.bop_mask()
    if count != B_COUNT:
        return False
    bops.mask = mask
    return True


def _cruby_owns(bit):
    return bops.mask & (1 << bit) == 0


def _int_op(bit):
    """CRuby still owns the operator and RPyYARV hasn't defined one; the registry lookup is elidable on the method version, invalidated by a later `class Integer`."""
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_INTEGER),
                                     _INT_MID[bit]) is None)


def _ary_op(bit):
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_ARRAY),
                                     _ARY_MID[bit - B_ARY_AREF]) is None)


def _sym_op(bit):
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_SYMBOL),
                                     _SYM_MID[bit - B_SYM_EQ]) is None)


def _flt_op(bit):
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_FLOAT),
                                     _FLT_MID[bit - B_FLT_PLUS]) is None)


def _from_int(n):
    if value.fixable(n):
        return value.int2fix(n)
    return rubycall.to_bignum(n)


def _fix2(a, b, bit):
    return value.is_fixnum(a) and value.is_fixnum(b) and _int_op(bit)


# Above this a Fixnum no longer converts to a double exactly, and the
# comparisons CRuby answers with rb_integer_float_cmp would disagree.
FLOAT_EXACT_INT = 1 << 53


def _mixable(v, exact):
    if not value.is_fixnum(v):
        return False
    if not exact:
        return True
    n = value.fix2int(v)
    return n >= -FLOAT_EXACT_INT and n <= FLOAT_EXACT_INT


def _flt2(a, b, bit, exact=False):
    """One Float operand and one Float or Fixnum, with the receiver's own class still owning the operator; a Bignum falls back, as CRuby's Float methods reach rb_big2dbl for it."""
    if value.is_float(a):
        if not (value.is_float(b) or _mixable(b, exact)):
            return False
        return _flt_op(bit)
    if value.is_float(b) and _mixable(a, exact):
        return _int_op(_FLT_AS_INT[bit - B_FLT_PLUS])
    return False


def _dbl(v):
    if value.is_fixnum(v):
        return float(value.fix2int(v))
    return value.float_val(v)


def _from_dbl(d):
    """A flonum when the encoding reaches d, else the heap Float DBL2NUM falls back to."""
    v = value.dbl2flonum(d)
    if v != value.Q_UNDEF:
        return v
    return rubycall.to_heap_float(d)


def add(a, b):
    if _fix2(a, b, B_INT_PLUS):
        return _from_int(value.fix2int(a) + value.fix2int(b))
    if _flt2(a, b, B_FLT_PLUS):
        return _from_dbl(_dbl(a) + _dbl(b))
    return value.Q_UNDEF


def sub(a, b):
    if _fix2(a, b, B_INT_MINUS):
        return _from_int(value.fix2int(a) - value.fix2int(b))
    if _flt2(a, b, B_FLT_MINUS):
        return _from_dbl(_dbl(a) - _dbl(b))
    return value.Q_UNDEF


def mul(a, b):
    if _fix2(a, b, B_INT_MULT):
        try:
            return _from_int(ovfcheck(value.fix2int(a) * value.fix2int(b)))
        except OverflowError:
            pass
    elif _flt2(a, b, B_FLT_MULT):
        return _from_dbl(_dbl(a) * _dbl(b))
    return value.Q_UNDEF


def lt(a, b):
    if _fix2(a, b, B_INT_LT):
        return value.newbool(value.fix2int(a) < value.fix2int(b))
    if _flt2(a, b, B_FLT_LT, True):
        return value.newbool(_dbl(a) < _dbl(b))
    return value.Q_UNDEF


def gt(a, b):
    if _fix2(a, b, B_INT_GT):
        return value.newbool(value.fix2int(a) > value.fix2int(b))
    if _flt2(a, b, B_FLT_GT, True):
        return value.newbool(_dbl(a) > _dbl(b))
    return value.Q_UNDEF


def le(a, b):
    if _fix2(a, b, B_INT_LE):
        return value.newbool(value.fix2int(a) <= value.fix2int(b))
    if _flt2(a, b, B_FLT_LE, True):
        return value.newbool(_dbl(a) <= _dbl(b))
    return value.Q_UNDEF


def ge(a, b):
    if _fix2(a, b, B_INT_GE):
        return value.newbool(value.fix2int(a) >= value.fix2int(b))
    if _flt2(a, b, B_FLT_GE, True):
        return value.newbool(_dbl(a) >= _dbl(b))
    return value.Q_UNDEF


def math_sqrt(recv, arg):
    """Math.sqrt of a non-negative Float or Fixnum; a negative one keeps CRuby's Math::DomainError (math.c:765)."""
    if recv != value.core_class(value.C_MATH) or not _cruby_owns(B_MATH_SQRT):
        return value.Q_UNDEF
    if not (value.is_float(arg) or value.is_fixnum(arg)):
        return value.Q_UNDEF
    d = _dbl(arg)
    if d < 0.0:
        return value.Q_UNDEF
    if d == 0.0:
        return _from_dbl(0.0)
    return _from_dbl(math.sqrt(d))


def _sym_eq(a, mid):
    """Symbol#== is rb_obj_equal (string.c:12227) and a name has exactly one Symbol VALUE, so a word compare answers it."""
    if value.class_of(a) != value.core_class(value.C_SYMBOL):
        return False
    if not _sym_op(B_SYM_EQ):
        return False
    if mid == NEQ:
        return dispatch.owns_identity(value.core_class(value.C_SYMBOL), NEQ)
    return True


def identity_op(recv, mid):
    """vm_opt_equality's second half: the receiver still resolves the operator to BasicObject's, so comparing is comparing the words."""
    klass = value.class_of(recv)
    if klass == 0:
        return False
    klass = promote(klass)
    if mid == NEQ:
        # BasicObject#!= is defined in terms of #==, so both must be untouched.
        return (dispatch.owns_identity(klass, NEQ)
                and dispatch.owns_identity(klass, EQ))
    return dispatch.owns_identity(klass, mid)


def identity_send(recv, mid):
    """==, != or equal? that comes down to comparing the two words."""
    if mid != EQUAL_P and _sym_eq(recv, mid):
        return True
    return identity_op(recv, mid)


def eq(a, b):
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a == b)
    if _flt2(a, b, B_FLT_EQ, True):
        return value.newbool(_dbl(a) == _dbl(b))
    if identity_send(a, EQ):
        return value.newbool(a == b)
    return value.Q_UNDEF


def neq(a, b):
    # BOP_NEQ is never flagged: vm_opt_neq resolves `!=` to BasicObject#!= then asks opt_equality, so Integer#== is the definition that counts.
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a != b)
    if _flt2(a, b, B_FLT_EQ, True):
        return value.newbool(_dbl(a) != _dbl(b))
    if identity_send(a, NEQ):
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


def xor(a, b):
    # Both tag bits are set, so the xor clears one that has to be put back.
    if _fix2(a, b, B_INT_XOR):
        return (a ^ b) | value.FIXNUM_FLAG
    return value.Q_UNDEF


def rshift(a, b):
    """Integer#>> for a non-negative fixnum shift; a negative one is a left shift CRuby may widen to a Bignum, so it goes back to CRuby."""
    if _fix2(a, b, B_INT_RSHIFT):
        n = value.fix2int(a)
        s = value.fix2int(b)
        if s >= 0:
            # A fixnum is under 63 bits, so any wider shift is already the sign; RPython leaves a shift of the full word width undefined.
            if s >= LONG_BIT - 1:
                s = LONG_BIT - 1
            return value.int2fix(n >> s)
    return value.Q_UNDEF


def range_part(recv, mid):
    """Range#begin, #end, #exclude_end? read straight off the Range; the shim answers Qundef for anything but a direct Range instance."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if mid == BEGIN and _cruby_owns(B_RNG_BEGIN):
        return boot.range_part(recv, boot.RANGE_BEG)
    if mid == END and _cruby_owns(B_RNG_END):
        return boot.range_part(recv, boot.RANGE_END)
    if mid == EXCLUDE_END_P and _cruby_owns(B_RNG_EXCL):
        return boot.range_part(recv, boot.RANGE_EXCL)
    return value.Q_UNDEF


def _both_positive(a, b):
    # Ruby's / and % floor, RPython's truncate: only take operands where the two agree.
    return (value.is_fixnum(a) and value.is_fixnum(b)
            and value.fix2int(a) >= 0 and value.fix2int(b) > 0)


def _fdiv(x, y):
    """Float#/ never raises: a zero denominator gives NaN or a signed Infinity (numeric.c:1150)."""
    if y != 0.0:
        return x / y
    if x == 0.0:
        return NAN
    return x * math.copysign(INFINITY, y)


def div(a, b):
    if _both_positive(a, b) and _int_op(B_INT_DIV):
        return value.int2fix(value.fix2int(a) // value.fix2int(b))
    if _flt2(a, b, B_FLT_DIV):
        return _from_dbl(_fdiv(_dbl(a), _dbl(b)))
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
    # TODO: vm_opt_not asks whether `!` still resolves to rb_obj_not, which no BOP flag records, so a redefined #! is still ignored here.
    return value.newbool(not value.is_true(recv))


def check_float_layout():
    """The Float fast paths decode flonums and read RFloat by hand; refuse a CRuby they misread."""
    got = boot.float_layout()
    return got == [value.FLOAT_VALUE_WORD, 1, 1]


def check_flonum_encoding():
    """value.dbl2flonum against DBL2NUM itself, on the doubles the rotation reaches and the ones it does not."""
    for d in [0.0, -0.0, 1.0, -1.0, 0.5, 1e-10, 1e10, 3.141592653589793,
              1.727233711018889e-77, 1.7272337110188893e-77, 1e300, 1e-300,
              INFINITY, -INFINITY]:
        want = boot.float_new(d)
        got = value.dbl2flonum(d)
        if value.is_flonum(want) != (got != value.Q_UNDEF):
            return False
        if got != value.Q_UNDEF and got != want:
            return False
        if value.float_val(want) != d and d == d:
            return False
    return True


def check_array_layout():
    """The Array fast paths read RArray by hand; refuse a CRuby they misread."""
    got = boot.array_layout()
    want = [value.ARY_EMBED_FLAG, value.ARY_EMBED_LEN_SHIFT,
            value.ARY_EMBED_LEN_MASK, value.ARY_HEAP_LEN_WORD,
            value.ARY_HEAP_PTR_WORD, value.ARY_EMBED_WORD]
    return got == want
