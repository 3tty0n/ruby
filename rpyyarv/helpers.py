"""The opt_* instructions: a fixnum or Array fast path that touches no rb_*
API, and a CRuby dispatch for everything else.

TODO: none of these consult CRuby's BOP redefinition flags, so reopening
Integer#+ or Array#[] is not observed.
"""

import boot
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


def neq(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return value.newbool(a != b)
    return rubycall.call1(a, NEQ, b)


def and_(a, b):
    # The tag bits are the same in both operands, so they survive the mask.
    if value.is_fixnum(a) and value.is_fixnum(b):
        return a & b
    return rubycall.call1(a, AND, b)


def or_(a, b):
    if value.is_fixnum(a) and value.is_fixnum(b):
        return a | b
    return rubycall.call1(a, OR, b)


def _both_positive(a, b):
    # Ruby's / and % floor, RPython's truncate: only take operands where the
    # two agree.
    return (value.is_fixnum(a) and value.is_fixnum(b)
            and value.fix2int(a) >= 0 and value.fix2int(b) > 0)


def div(a, b):
    if _both_positive(a, b):
        return value.int2fix(value.fix2int(a) // value.fix2int(b))
    return rubycall.call1(a, DIV, b)


def mod(a, b):
    if _both_positive(a, b):
        return value.int2fix(value.fix2int(a) % value.fix2int(b))
    return rubycall.call1(a, MOD, b)


def aref(recv, idx):
    """Array[Fixnum] reads the elements in place."""
    if value.is_plain_array(recv) and value.is_fixnum(idx):
        i = value.fix2int(idx)
        n = value.ary_len(recv)
        if i < 0:
            i += n
        if i >= 0 and i < n:
            return value.ary_at(recv, i)
        return value.Q_NIL
    return rubycall.call1(recv, AREF, idx)


def aset(recv, idx, val):
    if value.is_plain_array(recv) and value.is_fixnum(idx):
        rubycall.ary_store(recv, value.fix2int(idx), val)
        return val
    return rubycall.call2(recv, ASET, idx, val)


def length(recv):
    if value.is_plain_array(recv):
        return value.int2fix(value.ary_len(recv))
    return rubycall.call0(recv, LENGTH)


def size(recv):
    if value.is_plain_array(recv):
        return value.int2fix(value.ary_len(recv))
    return rubycall.call0(recv, SIZE)


def empty_p(recv):
    if value.is_plain_array(recv):
        return value.newbool(value.ary_len(recv) == 0)
    return rubycall.call0(recv, EMPTY_P)


def ltlt(recv, obj):
    return rubycall.call1(recv, LTLT, obj)


def opt_not(recv):
    # TODO: a redefined Object#! is ignored, unlike in CRuby.
    return value.newbool(not value.is_true(recv))


def check_array_layout():
    """The Array fast paths read RArray by hand; refuse a CRuby they misread."""
    got = boot.array_layout()
    want = [value.ARY_EMBED_FLAG, value.ARY_EMBED_LEN_SHIFT,
            value.ARY_EMBED_LEN_MASK, value.ARY_HEAP_LEN_WORD,
            value.ARY_HEAP_PTR_WORD, value.ARY_EMBED_WORD]
    return got == want
