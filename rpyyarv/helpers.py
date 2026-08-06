"""The opt_* arithmetic: a fixnum fast path that touches no rb_* API, and a
CRuby dispatch for everything else."""

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


def _from_int(n):
    if value.fixable(n):
        return value.int2fix(n)
    return rubycall.to_bignum(n)


def add(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return _from_int(value.fix2int(a) + value.fix2int(b))
    return rubycall.call1(a, PLUS, b)


def sub(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return _from_int(value.fix2int(a) - value.fix2int(b))
    return rubycall.call1(a, MINUS, b)


def mul(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        try:
            return _from_int(ovfcheck(value.fix2int(a) * value.fix2int(b)))
        except OverflowError:
            pass
    return rubycall.call1(a, MULT, b)


def lt(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return value.newbool(value.fix2int(a) < value.fix2int(b))
    return rubycall.call1(a, LT, b)


def gt(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return value.newbool(value.fix2int(a) > value.fix2int(b))
    return rubycall.call1(a, GT, b)


def le(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return value.newbool(value.fix2int(a) <= value.fix2int(b))
    return rubycall.call1(a, LE, b)


def ge(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return value.newbool(value.fix2int(a) >= value.fix2int(b))
    return rubycall.call1(a, GE, b)


def eq(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return value.newbool(a == b)
    return rubycall.call1(a, EQ, b)
