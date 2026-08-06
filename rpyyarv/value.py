"""VALUEs as plain signed machine words.

Signed is deliberate: FIX2LONG is an arithmetic right shift, which only a
signed type gets right. The tags below are compiled in; entry_point checks
them against rpyyarv_special_consts so a libruby with other tags fails at
startup instead of mis-decoding every VALUE.
"""

from rlib import LONG_BIT

Q_FALSE = 0x00
Q_NIL = 0x04
Q_TRUE = 0x14
Q_UNDEF = 0x24
FIXNUM_FLAG = 0x01
IMMEDIATE_MASK = 0x07

FIXNUM_MAX = (1 << (LONG_BIT - 2)) - 1
FIXNUM_MIN = -(1 << (LONG_BIT - 2))


def is_fixnum(v):
    return (v & FIXNUM_FLAG) != 0


def fix2int(v):
    return v >> 1


def fixable(n):
    return n >= FIXNUM_MIN and n <= FIXNUM_MAX


def int2fix(n):
    return (n << 1) | FIXNUM_FLAG


def is_true(v):
    return v != Q_FALSE and v != Q_NIL


def newbool(flag):
    if flag:
        return Q_TRUE
    return Q_FALSE


def is_immediate(v):
    # 0 is both Qfalse and a cleared stack slot; neither needs marking.
    return v == 0 or (v & IMMEDIATE_MASK) != 0


def repr_of(v):
    """A description that costs no rb_* call, for the debug channels."""
    if is_fixnum(v):
        return str(fix2int(v))
    if v == Q_NIL:
        return 'nil'
    if v == Q_TRUE:
        return 'true'
    if v == Q_FALSE:
        return 'false'
    if v == Q_UNDEF:
        return 'undef'
    return '<VALUE %d>' % v
