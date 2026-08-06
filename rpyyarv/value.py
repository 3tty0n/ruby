"""VALUEs as plain signed machine words.

Signed is deliberate: FIX2LONG is an arithmetic right shift, which only a
signed type gets right. The tags below are compiled in; entry_point checks
them against rpyyarv_special_consts so a libruby with other tags fails at
startup instead of mis-decoding every VALUE.
"""

from rlib import LONG_BIT, elidable, raw_word

Q_FALSE = 0x00
Q_NIL = 0x04
Q_TRUE = 0x14
Q_UNDEF = 0x24
FIXNUM_FLAG = 0x01
IMMEDIATE_MASK = 0x07
FLONUM_MASK = 0x03
FLONUM_FLAG = 0x02
SYMBOL_MASK = 0xff
SYMBOL_FLAG = 0x0c

# rbasic.h: flags then klass, one word each. RBASIC_SHAPE_ID_FIELD adds a
# third word only when SIZEOF_VALUE < 8, which RPyYARV does not support.
KLASS_WORD = 1
FLAGS_WORD = 0

# RObject layout for the ivar fast path; entry_point checks every one of these
# against rpyyarv_object_layout, so a drifting CRuby fails at startup.
SHAPE_SHIFT = 32                # shape.h: SHAPE_FLAG_SHIFT on 64-bit
SHAPE_ID_BITS = 32
SHAPE_MASK = (1 << SHAPE_ID_BITS) - 1
ROBJECT_HEAP = 1 << 16          # RUBY_FL_USER4: ivars spilled to a heap buffer
FIELDS_WORD = 2                 # struct RObject: as.ary / as.heap.fields
T_MASK = 0x1f
T_OBJECT = 0x01

# Slots of the table rpyyarv_core_classes fills, in its order.
C_OBJECT = 0
C_INTEGER = 1
C_FLOAT = 2
C_SYMBOL = 3
C_NILCLASS = 4
C_TRUECLASS = 5
C_FALSECLASS = 6
C_STRING = 7
C_ARRAY = 8
C_HASH = 9
C_CLASS = 10
C_MODULE = 11
NCLASS = 12

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


class _Classes(object):
    # Not _immutable_fields_: on a prebuilt instance the rtyper would fold
    # every read to the zeros this list holds before boot fills it.
    def __init__(self):
        self.tab = [0] * NCLASS


classes = _Classes()


def install_classes(tab):
    classes.tab = tab


@elidable
def core_class(i):
    """install_classes runs before any Ruby code, so this never changes."""
    return classes.tab[i]


def class_of(v):
    """The receiver's class VALUE. Immediates answer from the boot table, a
    heap object from its RBasic->klass word; neither costs an rb_* call.

    Heap objects are tested first: one guard, not the whole tag ladder, in
    front of the guard_value that makes a send site an inline cache."""
    if v != 0 and (v & IMMEDIATE_MASK) == 0:
        return raw_word(v, KLASS_WORD)
    if (v & FIXNUM_FLAG) != 0:
        return core_class(C_INTEGER)
    if (v & FLONUM_MASK) == FLONUM_FLAG:
        return core_class(C_FLOAT)
    if (v & SYMBOL_MASK) == SYMBOL_FLAG:
        return core_class(C_SYMBOL)
    if v == Q_FALSE:
        return core_class(C_FALSECLASS)
    if v == Q_NIL:
        return core_class(C_NILCLASS)
    if v == Q_TRUE:
        return core_class(C_TRUECLASS)
    return 0            # Qundef, or an immediate this build invented


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
