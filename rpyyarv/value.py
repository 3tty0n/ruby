"""VALUEs are signed machine words: FIX2LONG is an arithmetic right shift."""

from rpyyarv.rlib import (LONG_BIT, bits2float, elidable, float2bits, intmask,
                  r_uint, raw_word, set_raw_word)

# Header constants and struct offsets of the host CRuby, generated per
# version (host/hostconsts.c); the boot checks re-read them from libruby.
from rpyyarv.hostconsts import (
    Q_FALSE, Q_NIL, Q_TRUE, Q_UNDEF, FIXNUM_FLAG, IMMEDIATE_MASK,
    FLONUM_MASK, FLONUM_FLAG, SYMBOL_MASK, SYMBOL_FLAG,
    FLAGS_WORD, KLASS_WORD, FLOAT_VALUE_WORD,
    T_MASK, T_OBJECT, T_CLASS, T_MODULE, T_ARRAY, T_STRUCT, T_DATA,
    FL_FREEZE, FL_SINGLETON, FL_SHAREABLE, FL_TYPED_DATA,
    SHAPE_SHIFT, SHAPE_ID_BITS, SHAPE_ID_IN_FLAGS, FIELDS_WORD,
    IV_HEAP_MASK, IV_HEAP_BITS, IV_HEAP_BASE, IV_HEAP_IS_OBJECT,
    CLASS_FIELDS_WORD, RCLASS_BOXABLE,
    ARY_EMBED_FLAG, ARY_EMBED_LEN_SHIFT, ARY_EMBED_LEN_MASK,
    ARY_HEAP_LEN_WORD, ARY_HEAP_CAPA_WORD, ARY_HEAP_PTR_WORD,
    ARY_EMBED_WORD, ARY_SHARED_FLAG, ARY_SHARED_ROOT_FLAG,
    STRUCT_EMBED_LEN_SHIFT, STRUCT_EMBED_LEN_MASK, STRUCT_HEAP_LEN_WORD,
    STRUCT_HEAP_PTR_WORD, STRUCT_EMBED_WORD)

# The flonum encoding of internal/numeric.h, which rotates rather than shifts.
FLONUM_ZERO = -0x7ffffffffffffffe    # 0x8000000000000002, DBL2NUM(+0.0)
FLONUM_RESERVED = 0x3000000000000000  # rotates onto FLONUM_ZERO: heap only
FLONUM_ROT = 3

SHAPE_MASK = (1 << SHAPE_ID_BITS) - 1
SHAPE_FLAG_MASK = SHAPE_MASK    # shape.h: the flags bits a shape id write keeps

# Every header bit an ivar access decides on, so one guard covers all.
IV_HEADER_MASK = -(1 << SHAPE_SHIFT) | IV_HEAP_MASK | T_MASK
IV_SET_HEADER_MASK = IV_HEADER_MASK | FL_FREEZE


def struct_len(v):
    flags = raw_word(v, FLAGS_WORD)
    n = (flags & STRUCT_EMBED_LEN_MASK) >> STRUCT_EMBED_LEN_SHIFT
    if n != 0:
        return n
    return raw_word(v, STRUCT_HEAP_LEN_WORD)


def struct_at(v, i):
    """Caller has checked 0 <= i < struct_len(v)."""
    flags = raw_word(v, FLAGS_WORD)
    if flags & STRUCT_EMBED_LEN_MASK:
        return raw_word(v, STRUCT_EMBED_WORD + i)
    return raw_word(raw_word(v, STRUCT_HEAP_PTR_WORD), i)


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
C_MATH = 13                     # Math, receiver of the sqrt fast path
NCLASS = 14

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
    # Not _immutable_fields_: the rtyper would fold in the pre-boot zeros.
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
    """The receiver's class VALUE, without an rb_* call."""
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


def is_flonum(v):
    return (v & FLONUM_MASK) == FLONUM_FLAG


def is_heap_float(v):
    """A heap Float, as vm_opt_plus tests it (vm_insnhelper.c:6893)."""
    return (v != 0 and (v & IMMEDIATE_MASK) == 0
            and raw_word(v, KLASS_WORD) == core_class(C_FLOAT))


def is_float(v):
    return is_flonum(v) or is_heap_float(v)


def float_val(v):
    """The double in a checked Float VALUE (internal/numeric.h:249)."""
    if not is_flonum(v):
        return bits2float(raw_word(v, FLOAT_VALUE_WORD))
    if v == FLONUM_ZERO:
        return 0.0
    u = r_uint(v)
    # The exponent's top bit comes back from bit 63.
    x = (r_uint(2) - (u >> (LONG_BIT - 1))) | (u & ~r_uint(FLONUM_MASK))
    return bits2float(intmask((x >> FLONUM_ROT)
                              | (x << (LONG_BIT - FLONUM_ROT))))


def dbl2flonum(v):
    """The flonum for a double, else Q_UNDEF (internal/numeric.h:294)."""
    w = float2bits(v)
    u = r_uint(w)
    # Bits 62..60 must be 3 or 4; `exp3 == k` would pin one octave.
    exp3 = intmask(u >> (LONG_BIT - 4)) & 0x7
    if ((exp3 + 1) >> 1) == 2 and w != FLONUM_RESERVED:
        return intmask((((u << FLONUM_ROT)
                         | (u >> (LONG_BIT - FLONUM_ROT))) & ~r_uint(0x01))
                       | r_uint(FLONUM_FLAG))
    if w == 0:
        return FLONUM_ZERO
    return Q_UNDEF


def is_plain_array(v):
    """A direct Array instance: a subclass may have redefined #[]."""
    return (v != 0 and (v & IMMEDIATE_MASK) == 0
            and raw_word(v, KLASS_WORD) == core_class(C_ARRAY))


def is_array(v):
    return (v != 0 and (v & IMMEDIATE_MASK) == 0
            and raw_word(v, FLAGS_WORD) & T_MASK == T_ARRAY)


def is_plain_string(v):
    """A direct String instance: a subclass may have redefined #==."""
    return (v != 0 and (v & IMMEDIATE_MASK) == 0
            and raw_word(v, KLASS_WORD) == core_class(C_STRING))


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


def ary_writable(v):
    """What ARY_SET asserts (array.c:177), plus the shared root a view reads."""
    flags = raw_word(v, FLAGS_WORD)
    return (flags & (FL_FREEZE | ARY_SHARED_FLAG | ARY_SHARED_ROOT_FLAG)) == 0


def ary_set(v, i, val):
    """Caller checked ary_writable and bounds; the barrier is the caller's."""
    flags = raw_word(v, FLAGS_WORD)
    if flags & ARY_EMBED_FLAG:
        set_raw_word(v, ARY_EMBED_WORD + i, val)
    else:
        set_raw_word(raw_word(v, ARY_HEAP_PTR_WORD), i, val)


def ary_append_immediate(v, val):
    """Append without CRuby when the existing RArray storage has room."""
    flags = raw_word(v, FLAGS_WORD)
    if flags & (FL_FREEZE | ARY_SHARED_FLAG | ARY_SHARED_ROOT_FLAG):
        return False
    n = ary_len(v)
    if flags & ARY_EMBED_FLAG:
        return False
    if n >= raw_word(v, ARY_HEAP_CAPA_WORD):
        return False
    set_raw_word(raw_word(v, ARY_HEAP_PTR_WORD), n, val)
    set_raw_word(v, ARY_HEAP_LEN_WORD, n + 1)
    return True


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
