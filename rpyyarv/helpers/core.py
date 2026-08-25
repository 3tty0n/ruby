"""Shared bop/registry machinery every fast-path group depends on."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.rlib import promote


PLUS = symbols.intern('+')
MINUS = symbols.intern('-')
MULT = symbols.intern('*')
LT = symbols.intern('<')
GT = symbols.intern('>')
LE = symbols.intern('<=')
GE = symbols.intern('>=')
EQ = symbols.intern('==')
EQQ = symbols.intern('===')
NEQ = symbols.intern('!=')
EQUAL_P = symbols.intern('equal?')
DIV = symbols.intern('/')
MOD = symbols.intern('%')
AREF = symbols.intern('[]')
ASET = symbols.intern('[]=')
LENGTH = symbols.intern('length')
SIZE = symbols.intern('size')
EMPTY_P = symbols.intern('empty?')
BYTESIZE = symbols.intern('bytesize')
ASCII_ONLY_P = symbols.intern('ascii_only?')
LTLT = symbols.intern('<<')
AND = symbols.intern('&')
OR = symbols.intern('|')
XOR = symbols.intern('^')
RSHIFT = symbols.intern('>>')
BEGIN = symbols.intern('begin')
END = symbols.intern('end')
EXCLUDE_END_P = symbols.intern('exclude_end?')
SQRT = symbols.intern('sqrt')
INITIALIZE = symbols.intern('initialize')
ABS = symbols.intern('abs')
TO_ARY = symbols.intern('to_ary')
TO_STR = symbols.intern('to_str')
TO_I = symbols.intern('to_i')
UMINUS = symbols.intern('-@')
NIL_P = symbols.intern('nil?')
FREEZE = symbols.intern('freeze')
MIN = symbols.intern('min')
MAX = symbols.intern('max')
HASH = symbols.intern('hash')
PACK = symbols.intern('pack')
ROTATE_BANG = symbols.intern('rotate!')
COVER_P = symbols.intern('cover?')
MEMBER_P = symbols.intern('member?')
INCLUDE_P = symbols.intern('include?')
RESPOND_TO_P = symbols.intern('respond_to?')
POW = symbols.intern('**')
TO_F = symbols.intern('to_f')
TO_S = symbols.intern('to_s')
NAME = symbols.intern('name')
COS = symbols.intern('cos')
CASECMP = symbols.intern('casecmp')
TR = symbols.intern('tr')
INDEX_MID = symbols.intern('index')
MATCH_P = symbols.intern('match?')
POP_MID = symbols.intern('pop')
PUSH_MID = symbols.intern('push')
POS_MID = symbols.intern('pos')
POS_SET = symbols.intern('pos=')
EOS_P_MID = symbols.intern('eos?')
MATCHED_SIZE = symbols.intern('matched_size')
SKIP_MID = symbols.intern('skip')
BYTESLICE = symbols.intern('byteslice')
SPACESHIP = symbols.intern('<=>')
DIV_WORD = symbols.intern('div')
DOWNCASE = symbols.intern('downcase')
DOWNCASE_BANG = symbols.intern('downcase!')
UPCASE = symbols.intern('upcase')
UPCASE_BANG = symbols.intern('upcase!')
DUP = symbols.intern('dup')
KIND_OF_P = symbols.intern('kind_of?')
IS_A_P = symbols.intern('is_a?')
INSTANCE_EVAL = symbols.intern('instance_eval')
INSTANCE_EXEC = symbols.intern('instance_exec')
KEYS_MID = symbols.intern('keys')
SHIFT_MID = symbols.intern('shift')
UNSHIFT_MID = symbols.intern('unshift')
FLATTEN_BANG_MID = symbols.intern('flatten!')
GSUB = symbols.intern('gsub')
GSUB_BANG = symbols.intern('gsub!')
SUB = symbols.intern('sub')
SUB_BANG = symbols.intern('sub!')
MATCH_TILDE = symbols.intern('=~')
MATCH_MID = symbols.intern('match')
LAST_MATCH = symbols.intern('last_match')
FORMAT_MID = symbols.intern('format')
SPRINTF_MID = symbols.intern('sprintf')
ESCAPE_HTML_MID = symbols.intern('escapeHTML')


# RB_FIXABLE for a double (arithmetic/fixnum.h); bounds are exact powers of 2.
FIXNUM_MAX_PLUS_1_DBL = float(value.FIXNUM_MAX + 1)
FIXNUM_MIN_DBL = float(value.FIXNUM_MIN)


# One bit per (class, op), in boot_shim.c's rpyyarv_bop_mask order.
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
B_ARY_NEW = 33
B_ARY_INITIALIZE = 34
B_NIL_NIL_P = 35
B_STR_FREEZE = 36
B_STR_EQ = 37
B_KERNEL_SEND = 38
B_BASIC_SEND = 39
B_ARY_LTLT = 40
B_FLT_POW = 41
B_INT_POW = 42
B_MATH_COS = 43
B_INT_TO_F = 44
B_FLT_TO_F = 45
B_SYM_NAME = 46
B_BASIC_INITIALIZE = 47
B_STR_LTLT = 48
B_KERNEL_NIL_P = 49
B_BASIC_INSTANCE_EVAL = 50
B_BASIC_INSTANCE_EXEC = 51
B_HASH_AREF = 52
B_STR_TO_S = 53
B_KERNEL_EQQ = 54
B_KERNEL_KIND_OF = 55
B_KERNEL_IS_A = 56
B_HASH_ASET = 57
B_HASH_KEY = 58
B_HASH_HAS_KEY = 59
B_SET_INCLUDE = 60
B_STR_EQQ = 61
B_STR_START_WITH = 62
B_KERNEL_PUBLIC_SEND = 63
B_COUNT = 64


_INT_MID = [PLUS, MINUS, MULT, DIV, MOD, EQ, LT, LE, GT, GE, AND, OR, XOR,
            RSHIFT]
_ARY_MID = [AREF, ASET, LENGTH, SIZE, EMPTY_P]
_SYM_MID = [EQ]
_FLT_MID = [PLUS, MINUS, MULT, DIV, LT, LE, GT, GE, EQ]
# The Integer bit the same operator takes when the *receiver* is the Fixnum.
_FLT_AS_INT = [B_INT_PLUS, B_INT_MINUS, B_INT_MULT, B_INT_DIV, B_INT_LT,
               B_INT_LE, B_INT_GT, B_INT_GE, B_INT_EQ]


class _Bops(object):
    # Quasi-immutable: refresh() invalidates the guard a fast path folded in.
    _immutable_fields_ = ['mask?']

    def __init__(self):
        # Every bit set until refresh(): no fast path before CRuby is asked.
        self.mask = -1
        # RPYYARV_FAST_PATHS=0 keeps that state, disabling every opt_* path.
        self.disabled = False


bops = _Bops()


class _Modules(object):
    # Quasi-immutable: interp.install() writes it once before Ruby runs.
    _immutable_fields_ = ['kernel?']

    def __init__(self):
        self.kernel = 0


modules = _Modules()


def disable_fast_paths():
    """Startup-only switch; refresh() then leaves every opt_* path off."""
    bops.disabled = True


def refresh():
    """Re-ask CRuby for the watched operators; some redefinitions missed."""
    dispatch.invalidate_owners()
    count, mask = boot.bop_mask()
    if count != B_COUNT:
        return False
    # Left at -1 the fast paths never fire; only refresh() reads the switch,
    # so the per-send guard still folds on the quasi-immutable mask alone.
    if not bops.disabled:
        bops.mask = mask
    return True


def _cruby_owns(bit):
    return bops.mask & (1 << bit) == 0


def kernel_send_pristine():
    """Kernel#send is still rb_f_send, so a send may be resolved here."""
    return _cruby_owns(B_KERNEL_SEND)


def basic_send_pristine():
    return _cruby_owns(B_BASIC_SEND)


def kernel_public_send_pristine():
    """Kernel#public_send is still rb_f_public_send, so it resolves here."""
    return _cruby_owns(B_KERNEL_PUBLIC_SEND)


def _int_op(bit):
    """CRuby owns the op and RPyYARV defined none; elidable on the version."""
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_INTEGER),
                                     _INT_MID[bit]) is None)


def _ary_op(bit):
    if bit == B_ARY_LTLT:
        mid = LTLT
    else:
        mid = _ARY_MID[bit - B_ARY_AREF]
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_ARRAY),
                                     mid) is None)


def _sym_op(bit):
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(value.C_SYMBOL),
                                     _SYM_MID[bit - B_SYM_EQ]) is None)


def _str_eq_op():
    return (_cruby_owns(B_STR_EQ)
            and dispatch.lookup_core(value.core_class(value.C_STRING),
                                     EQ) is None)


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


# Above this a Fixnum is not exact as a double; rb_integer_float_cmp differs.
FLOAT_EXACT_INT = 1 << 53


def _mixable(v, exact):
    if not value.is_fixnum(v):
        return False
    if not exact:
        return True
    n = value.fix2int(v)
    return n >= -FLOAT_EXACT_INT and n <= FLOAT_EXACT_INT


def _flt2(a, b, bit, exact=False):
    """Float with Float/Fixnum, the class still owning it; Bignum goes back."""
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
    """A flonum when the encoding reaches d, else DBL2NUM's heap Float."""
    v = value.dbl2flonum(d)
    if v != value.Q_UNDEF:
        return v
    return rubycall.to_heap_float(d)


def _core_op(klass_i, bit, mid):
    """CRuby has its own definition and RPyYARV defined none over it."""
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(klass_i), mid) is None)


INSTANCE_OF_P = symbols.intern('instance_of?')
CLASS_MID = symbols.intern('class')
FROZEN_P = symbols.intern('frozen?')
KEY_P = symbols.intern('key?')
HAS_KEY_P = symbols.intern('has_key?')
INCLUDE_P = symbols.intern('include?')
START_WITH_P = symbols.intern('start_with?')


def _owned_by_core(recv, klass_i, mid):
    """CRuby's core method still answers mid; elidable on the version."""
    return dispatch.owner_of(promote(value.class_of(recv)),
                             mid) == value.core_class(klass_i)


def _int_owns(mid):
    """No BOP flag watches these, so ask CRuby who owns them."""
    klass = value.core_class(value.C_INTEGER)
    return (dispatch.owner_of(klass, mid) == klass
            and dispatch.lookup_core(klass, mid) is None)


def _flt_owns(mid):
    """No BOP flag watches these, so ask CRuby who owns them."""
    klass = value.core_class(value.C_FLOAT)
    return (dispatch.owner_of(klass, mid) == klass
            and dispatch.lookup_core(klass, mid) is None)
