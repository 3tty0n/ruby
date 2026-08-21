"""Integer and Float fast paths."""
from __future__ import absolute_import

import math

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.rlib import INFINITY, LONG_BIT, NAN, ovfcheck
from rpyyarv.helpers.core import *
from rpyyarv.helpers.core import (_ary_op, _core_op, _cruby_owns, _dbl,
                                  _fix2, _flt2, _flt_owns, _from_dbl,
                                  _from_int, _int_op, _int_owns,
                                  _owned_by_core)
from rpyyarv.helpers.string import str_concat


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


def math_cos(recv, arg):
    """Math.cos of Float/Fixnum; cos is total, so nothing can raise."""
    if recv != value.core_class(value.C_MATH) or not _cruby_owns(B_MATH_COS):
        return value.Q_UNDEF
    if not (value.is_float(arg) or value.is_fixnum(arg)):
        return value.Q_UNDEF
    return _from_dbl(math.cos(_dbl(arg)))


def int_pow(a, b):
    """Integer ** a non-negative Integer, while it stays exact in a word."""
    if not _fix2(a, b, B_INT_POW):
        return value.Q_UNDEF
    e = value.fix2int(b)
    if e < 0:
        return value.Q_UNDEF
    base = value.fix2int(a)
    r = 1
    try:
        while e > 0:
            if e & 1:
                r = ovfcheck(r * base)
            e >>= 1
            if e > 0:
                base = ovfcheck(base * base)
    except OverflowError:
        return value.Q_UNDEF
    if not value.fixable(r):
        return value.Q_UNDEF
    return value.int2fix(r)


def flt_pow(a, b):
    """Float **; a negative base gives a Complex and an overflow raises."""
    if not (value.is_float(a) or value.is_fixnum(a)):
        return value.Q_UNDEF
    if not (value.is_float(b) or value.is_fixnum(b)):
        return value.Q_UNDEF
    if value.is_float(a):
        if not _core_op(value.C_FLOAT, B_FLT_POW, POW):
            return value.Q_UNDEF
    else:
        # Integer ** Integer is exact and a negative exponent gives a Rational.
        if not value.is_float(b):
            return value.Q_UNDEF
        if not _core_op(value.C_INTEGER, B_INT_POW, POW):
            return value.Q_UNDEF
    x = _dbl(a)
    if x < 0.0:
        return value.Q_UNDEF
    try:
        return _from_dbl(math.pow(x, _dbl(b)))
    except (OverflowError, ValueError):
        return value.Q_UNDEF


def to_f(recv):
    """Integer#to_f and Float#to_f; a Bignum goes back to CRuby."""
    if value.is_float(recv):
        if _core_op(value.C_FLOAT, B_FLT_TO_F, TO_F):
            return recv
        return value.Q_UNDEF
    if value.is_fixnum(recv) and _core_op(value.C_INTEGER, B_INT_TO_F, TO_F):
        return _from_dbl(float(value.fix2int(recv)))
    return value.Q_UNDEF


def math_sqrt(recv, arg):
    """Math.sqrt of non-negative Float/Fixnum; negative raises (math.c:765)."""
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


def spaceship(recv, arg):
    """Integer#<=> of two fixnums, or String#<=> of two Strings."""
    if value.is_fixnum(recv) and value.is_fixnum(arg):
        if not _owned_by_core(recv, value.C_INTEGER, SPACESHIP):
            return value.Q_UNDEF
        a = value.fix2int(recv)
        b = value.fix2int(arg)
        return value.int2fix(-1 if a < b else (1 if a > b else 0))
    if not value.is_immediate(recv) and not value.is_immediate(arg) \
            and boot.is_string(recv):
        if not _owned_by_core(recv, value.C_STRING, SPACESHIP):
            return value.Q_UNDEF
        return boot.str_cmp(recv, arg)
    return value.Q_UNDEF


def int_div_word(recv, arg):
    """Integer#div of two fixnums; RPython's // floors as Ruby's does."""
    if not (value.is_fixnum(recv) and value.is_fixnum(arg)):
        return value.Q_UNDEF
    b = value.fix2int(arg)
    # ZeroDivisionError, and FIXNUM_MIN // -1 overflows; both go back.
    if b == 0 or b == -1:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_INTEGER, DIV_WORD):
        return value.Q_UNDEF
    return value.int2fix(value.fix2int(recv) // b)


def int_to_s(recv):
    """Integer#to_s with no base argument, for a FIXNUM receiver."""
    if not value.is_fixnum(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_INTEGER, TO_S):
        return value.Q_UNDEF
    return boot.int_to_s(recv)


def int_eqq(a, b):
    """Integer#=== for two Fixnums; unlike ==, === has no CRuby BOP flag."""
    if value.is_fixnum(a) and value.is_fixnum(b) and _int_owns(EQQ):
        return value.newbool(a == b)
    return value.Q_UNDEF


def int_eqq_pristine():
    return _int_owns(EQQ)


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
    """Integer#>> for a non-negative shift; a negative one may widen."""
    if _fix2(a, b, B_INT_RSHIFT):
        n = value.fix2int(a)
        s = value.fix2int(b)
        if s >= 0:
            # A fixnum is under 63 bits; a full-word shift is undefined.
            if s >= LONG_BIT - 1:
                s = LONG_BIT - 1
            return value.int2fix(n >> s)
    return value.Q_UNDEF


def int_abs(recv):
    """Integer#abs for a Fixnum; no BOP flag, so ask CRuby who owns it."""
    if not value.is_fixnum(recv):
        return value.Q_UNDEF
    klass = value.core_class(value.C_INTEGER)
    if dispatch.owner_of(klass, ABS) != klass \
            or dispatch.lookup_core(klass, ABS) is not None:
        return value.Q_UNDEF
    n = value.fix2int(recv)
    if n >= 0:
        return recv
    # The fixnum minimum negates to a Bignum, which only CRuby builds.
    if not value.fixable(-n):
        return value.Q_UNDEF
    return value.int2fix(-n)


def int_uminus(recv):
    """Integer#-@; the fixnum minimum negates to a CRuby-only Bignum."""
    if not value.is_fixnum(recv) or not _int_owns(UMINUS):
        return value.Q_UNDEF
    n = -value.fix2int(recv)
    if not value.fixable(n):
        return value.Q_UNDEF
    return value.int2fix(n)


def int_bitref(a, b):
    """Integer#[] non-negative index; Range or negative (numeric.c:5001)."""
    if not (value.is_fixnum(a) and value.is_fixnum(b)) or not _int_owns(AREF):
        return value.Q_UNDEF
    s = value.fix2int(b)
    if s < 0:
        return value.Q_UNDEF
    # A fixnum is under 63 bits, so any wider index reads the sign.
    if s >= LONG_BIT - 1:
        s = LONG_BIT - 1
    return value.int2fix((value.fix2int(a) >> s) & 1)


def lshift(a, b):
    """The Integer, Array and String arms of vm_opt_ltlt."""
    if value.is_plain_array(a) and _ary_op(B_ARY_LTLT):
        if value.is_immediate(b) and value.ary_append_immediate(a, b):
            return a
        rubycall.ary_store(a, value.ary_len(a), b)
        return a
    if not (value.is_fixnum(a) and value.is_fixnum(b)) or not _int_owns(LTLT):
        return str_concat(a, b)
    n = value.fix2int(a)
    s = value.fix2int(b)
    if s < 0 or s > LONG_BIT - 2:
        return value.Q_UNDEF
    # Bound the operand first: an overflowing shift is undefined in RPython.
    limit = 1 << (LONG_BIT - 2 - s)
    if n >= limit or n < -limit:
        return value.Q_UNDEF
    return value.int2fix(n << s)


def flt_to_i(recv):
    """flo_to_i (numeric.c:2562) truncates; NaN, inf and wide values back."""
    if not value.is_float(recv) or not _flt_owns(TO_I):
        return value.Q_UNDEF
    d = value.float_val(recv)
    if d > 0.0:
        d = math.floor(d)
    elif d < 0.0:
        d = math.ceil(d)
    if not (d >= FIXNUM_MIN_DBL and d < FIXNUM_MAX_PLUS_1_DBL):
        return value.Q_UNDEF
    return value.int2fix(int(d))


def flt_uminus(recv):
    """rb_float_uminus (numeric.c:1048) is an IEEE negate: 0.0/-0.0 swap."""
    if not value.is_float(recv) or not _flt_owns(UMINUS):
        return value.Q_UNDEF
    return _from_dbl(-value.float_val(recv))


def _both_positive(a, b):
    # Ruby's / and % floor, RPython's truncate: take only where they agree.
    return (value.is_fixnum(a) and value.is_fixnum(b)
            and value.fix2int(a) >= 0 and value.fix2int(b) > 0)


def _fdiv(x, y):
    """Float#/ never raises: /0 is NaN or a signed Inf (numeric.c:1150)."""
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


def check_float_layout():
    """Float fast paths read RFloat by hand; refuse a CRuby they misread."""
    got = boot.float_layout()
    return got == [value.FLOAT_VALUE_WORD, 1, 1]


def check_flonum_encoding():
    """value.dbl2flonum against DBL2NUM, on and off the rotation's range."""
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
