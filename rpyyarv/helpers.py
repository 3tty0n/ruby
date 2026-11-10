import math

from rpyyarv.error import UnsupportedOperation
from rpyyarv.objects.float import W_Float, w_pow
from rpyyarv.objects.klass import w_float_class, w_integer_class
from rpyyarv.objects.string import W_String
from rpyyarv.objects.transparent import (W_Bignum, W_Integer, bigint_of,
                                         newbig, newbool, newint)
from rpyyarv.rlib import ovfcheck, rbigint

INF = float('inf')
NAN = float('nan')
TWO_63 = 9223372036854775808.0
UNORDERED = 2

# Interface contract C2: wrapped in, wrapped out. A Float operand makes both
# sides Floats, as in CRuby; other non-integer operands make int_w() raise
# UnsupportedOperation from W_Root. An Integer result beyond 64 bits becomes
# a W_Bignum, and one that fits again a machine word.


def is_number(w_x):
    return isinstance(w_x, W_Integer) or isinstance(w_x, W_Float)


def numeric_fast(w_a, w_b, bop):
    if isinstance(w_a, W_Integer):
        w_class = w_integer_class
    elif isinstance(w_a, W_Float):
        w_class = w_float_class
    else:
        return False
    return is_number(w_b) and w_class.redefined & bop == 0


def _floats(w_a, w_b):
    return isinstance(w_a, W_Float) or isinstance(w_b, W_Float)


def _bigs(w_a, w_b):
    return isinstance(w_a, W_Bignum) or isinstance(w_b, W_Bignum)


def w_add(w_a, w_b):
    if isinstance(w_a, W_String) and isinstance(w_b, W_String):
        return W_String(w_a.str_w() + w_b.str_w())
    if _floats(w_a, w_b):
        return W_Float(w_a.float_w() + w_b.float_w())
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).add(bigint_of(w_b)))
    a = w_a.int_w()
    b = w_b.int_w()
    try:
        r = ovfcheck(a + b)
    except OverflowError:
        return newbig(rbigint.fromint(a).add(rbigint.fromint(b)))
    return newint(r)

def w_sub(w_a, w_b):
    if _floats(w_a, w_b):
        return W_Float(w_a.float_w() - w_b.float_w())
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).sub(bigint_of(w_b)))
    a = w_a.int_w()
    b = w_b.int_w()
    try:
        r = ovfcheck(a - b)
    except OverflowError:
        return newbig(rbigint.fromint(a).sub(rbigint.fromint(b)))
    return newint(r)


def w_mul(w_a, w_b):
    if _floats(w_a, w_b):
        return W_Float(w_a.float_w() * w_b.float_w())
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).mul(bigint_of(w_b)))
    a = w_a.int_w()
    b = w_b.int_w()
    try:
        r = ovfcheck(a * b)
    except OverflowError:
        return newbig(rbigint.fromint(a).mul(rbigint.fromint(b)))
    return newint(r)


# 1 << 34, rb_big_pow's limit on the result's bits on a 64-bit CRuby
BIGLEN_LIMIT = 17179869184


def _big_pow(w_a, b):
    big = bigint_of(w_a)
    bits = big.bit_length()
    if bits > BIGLEN_LIMIT // b:
        raise UnsupportedOperation('exponent is too large (ArgumentError)')
    return newbig(big.pow(rbigint.fromint(b)))


def w_int_pow(w_a, w_b):
    if isinstance(w_b, W_Float):
        return w_pow(W_Float(w_a.float_w()), w_b)
    if isinstance(w_b, W_Bignum):
        raise UnsupportedOperation('exponent is too large (ArgumentError)')
    b = w_b.int_w()
    if isinstance(w_a, W_Bignum):
        if b < 0:
            raise UnsupportedOperation(
                '%s ** %s is a Rational: RPyYARV has no Rational yet'
                % (w_a.repr(), w_b.repr()))
        if b == 0:
            return newint(1)
        return _big_pow(w_a, b)
    a = w_a.int_w()
    if a == 1:
        return newint(1)
    if a == -1:
        return newint(-1 if b % 2 != 0 else 1)
    if b < 0:
        if a == 0:
            raise UnsupportedOperation('divided by 0 (ZeroDivisionError)')
        raise UnsupportedOperation(
            '%s ** %s is a Rational: RPyYARV has no Rational yet'
            % (w_a.repr(), w_b.repr()))
    if b == 0:
        return newint(1)
    if b == 1:
        return w_a
    if a == 0:
        return newint(0)
    r = 1
    try:
        while b > 0:
            if b & 1:
                r = ovfcheck(r * a)
            b >>= 1
            if b > 0:
                a = ovfcheck(a * a)
    except OverflowError:
        return _big_pow(w_a, w_b.int_w())
    return newint(r)


def w_and(w_a, w_b):
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).and_(bigint_of(w_b)))
    return newint(w_a.int_w() & w_b.int_w())


def w_or(w_a, w_b):
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).or_(bigint_of(w_b)))
    return newint(w_a.int_w() | w_b.int_w())


def w_xor(w_a, w_b):
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).xor(bigint_of(w_b)))
    return newint(w_a.int_w() ^ w_b.int_w())


def _shift_width(w_b):
    if isinstance(w_b, W_Bignum):
        raise UnsupportedOperation('a shift by a Bignum is not supported yet')
    return w_b.int_w()


def _lshift(w_a, n):
    # n < 0 only when negating the smallest width wrapped around
    if n < 0 or n > BIGLEN_LIMIT:
        raise UnsupportedOperation('shift width too big (RangeError)')
    if not isinstance(w_a, W_Bignum) and n < 63:
        a = w_a.int_w()
        top = a >> (63 - n)
        if top == 0 or top == -1:
            return newint(a << n)
    return newbig(bigint_of(w_a).lshift(n))


def _rshift(w_a, n):
    if isinstance(w_a, W_Bignum):
        return newbig(w_a.big.rshift(n))
    a = w_a.int_w()
    if n >= 63 or n < 0:
        return newint(-1 if a < 0 else 0)
    return newint(a >> n)


def w_lshift(w_a, w_b):
    n = _shift_width(w_b)
    if n < 0:
        return _rshift(w_a, -n)
    return _lshift(w_a, n)


def w_rshift(w_a, w_b):
    n = _shift_width(w_b)
    if n < 0:
        return _lshift(w_a, -n)
    return _rshift(w_a, n)


def _float_div(x, y):
    if y == 0.0:
        if x == 0.0 or math.isnan(x):
            return NAN
        return math.copysign(INF, x) * math.copysign(1.0, y)
    return x / y


def _float_mod(x, y):
    if y == 0.0:
        raise UnsupportedOperation('divided by 0 (ZeroDivisionError)')
    if math.isinf(x):
        return NAN
    r = math.fmod(x, y)
    if r != 0.0 and (r < 0.0) != (y < 0.0):
        r += y
    return r


def _zero_division(w_b):
    if not isinstance(w_b, W_Bignum) and w_b.int_w() == 0:
        raise UnsupportedOperation('divided by 0 (ZeroDivisionError)')


def w_div(w_a, w_b):
    if _floats(w_a, w_b):
        return W_Float(_float_div(w_a.float_w(), w_b.float_w()))
    _zero_division(w_b)
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).floordiv(bigint_of(w_b)))
    a = w_a.int_w()
    b = w_b.int_w()
    try:
        r = ovfcheck(a // b)
    except OverflowError:
        return newbig(rbigint.fromint(a).floordiv(rbigint.fromint(b)))
    return newint(r)


def w_mod(w_a, w_b):
    if _floats(w_a, w_b):
        return W_Float(_float_mod(w_a.float_w(), w_b.float_w()))
    _zero_division(w_b)
    if _bigs(w_a, w_b):
        return newbig(bigint_of(w_a).mod(bigint_of(w_b)))
    a = w_a.int_w()
    b = w_b.int_w()
    if b == -1:
        return newint(0)
    return newint(a % b)


def _int_float_cmp(i, f):
    if math.isnan(f):
        return UNORDERED
    if f >= TWO_63:
        return -1
    if f < -TWO_63:
        return 1
    whole = math.floor(f)
    n = int(whole)
    if i < n:
        return -1
    if i > n:
        return 1
    if f > whole:
        return -1
    return 0


def _big_float_cmp(big, f):
    if math.isnan(f):
        return UNORDERED
    if math.isinf(f):
        return -1 if f > 0.0 else 1
    whole = math.floor(f)
    w = rbigint.fromfloat(whole)
    if big.lt(w):
        return -1
    if big.gt(w):
        return 1
    if f > whole:
        return -1
    return 0


def _integer_float_cmp(w_i, f):
    if isinstance(w_i, W_Bignum):
        return _big_float_cmp(w_i.big, f)
    return _int_float_cmp(w_i.int_w(), f)


def _big_cmp(w_a, w_b):
    a = bigint_of(w_a)
    b = bigint_of(w_b)
    if a.lt(b):
        return -1
    if a.gt(b):
        return 1
    return 0


def _float_cmp(w_a, w_b):
    a_float = isinstance(w_a, W_Float)
    if a_float and isinstance(w_b, W_Float):
        x = w_a.float_w()
        y = w_b.float_w()
        if x < y:
            return -1
        if x > y:
            return 1
        if x == y:
            return 0
        return UNORDERED
    if a_float:
        c = _integer_float_cmp(w_b, w_a.float_w())
        if c == UNORDERED:
            return c
        return -c
    return _integer_float_cmp(w_a, w_b.float_w())


def w_lt(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(_float_cmp(w_a, w_b) == -1)
    if _bigs(w_a, w_b):
        return newbool(_big_cmp(w_a, w_b) == -1)
    return newbool(w_a.int_w() < w_b.int_w())


def w_gt(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(_float_cmp(w_a, w_b) == 1)
    if _bigs(w_a, w_b):
        return newbool(_big_cmp(w_a, w_b) == 1)
    return newbool(w_a.int_w() > w_b.int_w())


def w_le(w_a, w_b):
    if _floats(w_a, w_b):
        c = _float_cmp(w_a, w_b)
        return newbool(c == -1 or c == 0)
    if _bigs(w_a, w_b):
        return newbool(_big_cmp(w_a, w_b) <= 0)
    return newbool(w_a.int_w() <= w_b.int_w())


def w_ge(w_a, w_b):
    if _floats(w_a, w_b):
        c = _float_cmp(w_a, w_b)
        return newbool(c == 0 or c == 1)
    if _bigs(w_a, w_b):
        return newbool(_big_cmp(w_a, w_b) >= 0)
    return newbool(w_a.int_w() >= w_b.int_w())


def w_eq(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(_float_cmp(w_a, w_b) == 0)
    if _bigs(w_a, w_b):
        return newbool(_big_cmp(w_a, w_b) == 0)
    return newbool(w_a.int_w() == w_b.int_w())
