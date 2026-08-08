"""VALUEs as plain signed machine words: FIX2LONG is an arithmetic right shift, which only a signed type gets right; entry_point checks the tags below against rpyyarv_special_consts at startup."""

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

# rbasic.h: flags then klass, one word each (SIZEOF_VALUE == 8 only).
KLASS_WORD = 1
FLAGS_WORD = 0

# RObject layout for the ivar fast path, checked against rpyyarv_object_layout.
SHAPE_SHIFT = 32                # shape.h: SHAPE_FLAG_SHIFT on 64-bit
SHAPE_ID_BITS = 32
SHAPE_MASK = (1 << SHAPE_ID_BITS) - 1
ROBJECT_HEAP = 1 << 16          # RUBY_FL_USER4: ivars spilled to a heap buffer
FIELDS_WORD = 2                 # struct RObject: as.ary / as.heap.fields
T_MASK = 0x1f
T_OBJECT = 0x01
FL_FREEZE = 1 << 11             # RUBY_FL_FREEZE, the bit rb_check_frozen reads

# RArray layout for opt_aref/opt_length, checked against rpyyarv_array_layout: ARY_EMBED_FLAG says whether the array embeds its elements or not.
ARY_EMBED_FLAG = 1 << 13         # RUBY_FL_USER1
ARY_EMBED_LEN_SHIFT = 15         # RUBY_FL_USHIFT + 3
ARY_EMBED_LEN_MASK = 0x7f << ARY_EMBED_LEN_SHIFT
ARY_HEAP_LEN_WORD = 2
ARY_HEAP_PTR_WORD = 4
ARY_EMBED_WORD = 2

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
C_BASIC_OBJECT = 12
NCLASS = 13

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
    # Not _immutable_fields_: the rtyper would fold every read of this prebuilt instance to the zeros the list holds before boot fills it.
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
    """The receiver's class VALUE, without an rb_* call; heap objects are tested first, one guard in front of the send site's guard_value."""
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


def is_plain_array(v):
    """A direct Array instance: a subclass may have redefined #[]."""
    return (v != 0 and (v & IMMEDIATE_MASK) == 0
            and raw_word(v, KLASS_WORD) == core_class(C_ARRAY))


def ary_len(v):
    flags = raw_word(v, FLAGS_WORD)
    if flags & ARY_EMBED_FLAG:
        return (flags & ARY_EMBED_LEN_MASK) >> ARY_EMBED_LEN_SHIFT
    return raw_word(v, ARY_HEAP_LEN_WORD)


def ary_at(v, i):
    """Caller has checked 0 <= i < ary_len(v)."""
    flags = raw_word(v, FLAGS_WORD)
    if flags & ARY_EMBED_FLAG:
        return raw_word(v, ARY_EMBED_WORD + i)
    return raw_word(raw_word(v, ARY_HEAP_PTR_WORD), i)


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
