"""opt_* instructions: a fixnum/Array fast path touching no rb_* API, else value.Q_UNDEF as vm_opt_plus and friends do (vm_insnhelper.c:6880), so interp.py runs the real send."""

import math

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.rlib import (INFINITY, LONG_BIT, NAN, ovfcheck, promote,
                          raw_word)

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

# RB_FIXABLE for a double (arithmetic/fixnum.h); both bounds are exact powers of two.
FIXNUM_MAX_PLUS_1_DBL = float(value.FIXNUM_MAX + 1)
FIXNUM_MIN_DBL = float(value.FIXNUM_MIN)

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
B_COUNT = 63

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


class _Modules(object):
    # Quasi-immutable: interp.install() writes it once, before any Ruby code runs.
    _immutable_fields_ = ['kernel?']

    def __init__(self):
        self.kernel = 0


modules = _Modules()


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


def kernel_send_pristine():
    """Kernel#send is still rb_f_send, so a send may be resolved here instead."""
    return _cruby_owns(B_KERNEL_SEND)


def basic_send_pristine():
    return _cruby_owns(B_BASIC_SEND)


def _int_op(bit):
    """CRuby still owns the operator and RPyYARV hasn't defined one; the registry lookup is elidable on the method version, invalidated by a later `class Integer`."""
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


def math_cos(recv, arg):
    """Math.cos of a Float or Fixnum; cos is total over the reals, so only the receiver and the argument type are tested."""
    if recv != value.core_class(value.C_MATH) or not _cruby_owns(B_MATH_COS):
        return value.Q_UNDEF
    if not (value.is_float(arg) or value.is_fixnum(arg)):
        return value.Q_UNDEF
    return _from_dbl(math.cos(_dbl(arg)))


def _core_op(klass_i, bit, mid):
    """CRuby still has its own definition and RPyYARV has not defined one over it, as _int_op tests the operators."""
    return (_cruby_owns(bit)
            and dispatch.lookup_core(value.core_class(klass_i), mid) is None)


def flt_pow(a, b):
    """x ** y with a Float operand; a negative base with a fractional exponent is a Complex in Ruby, and an overflow raises here, so both go back to CRuby."""
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
    """Integer#to_f and Float#to_f; a Bignum's magnitude is CRuby's to convert."""
    if value.is_float(recv):
        if _core_op(value.C_FLOAT, B_FLT_TO_F, TO_F):
            return recv
        return value.Q_UNDEF
    if value.is_fixnum(recv) and _core_op(value.C_INTEGER, B_INT_TO_F, TO_F):
        return _from_dbl(float(value.fix2int(recv)))
    return value.Q_UNDEF


def _hash_key_cannot_reenter(key):
    """Immediates and plain Strings hash and compare in C, so a lookup with one never runs Ruby and needs no rb_protect."""
    return value.is_immediate(key) or value.is_plain_string(key)


def hash_aref(recv, key):
    """Hash#[] whole in one protected call, the default value or proc included, so a miss no longer pays a second full send."""
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    if not _core_op(value.C_HASH, B_HASH_AREF, AREF):
        return value.Q_UNDEF
    if _hash_key_cannot_reenter(key):
        v = boot.hash_lookup_fast(recv, key)
        if v != value.Q_UNDEF:
            return v
        # A miss still consults the default below, under rb_protect.
    return boot.hash_aref_value(recv, key)


def str_to_s(recv):
    """String#to_s is the receiver itself, but only for a direct String: a subclass answers a new String (string.c:11845)."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _core_op(value.C_STRING, B_STR_TO_S, TO_S):
        return value.Q_UNDEF
    return recv


def sym_name(recv):
    """Symbol#name is the symbol's own frozen String, one per symbol (symbol.c), so the cache is as permanent as the symbol."""
    if (recv & value.SYMBOL_MASK) != value.SYMBOL_FLAG:
        return value.Q_UNDEF
    if not _core_op(value.C_SYMBOL, B_SYM_NAME, NAME):
        return value.Q_UNDEF
    return dispatch.sym_name(recv)


def instance_eval_pristine(mid):
    """BasicObject#instance_eval/#instance_exec are still CRuby's own; a `def` on BasicObject is invisible to a walk from the receiver's class, so the registry is asked too."""
    if mid == INSTANCE_EVAL:
        return _core_op(value.C_BASIC_OBJECT, B_BASIC_INSTANCE_EVAL,
                        INSTANCE_EVAL)
    return _core_op(value.C_BASIC_OBJECT, B_BASIC_INSTANCE_EXEC, INSTANCE_EXEC)


def basic_initialize_pristine():
    """BasicObject#initialize is still rb_obj_dummy_initialize: no argument, no effect, nil."""
    return _cruby_owns(B_BASIC_INITIALIZE)


def basic_initialize(klass):
    """The receiver inherits BasicObject#initialize, which takes no argument and does nothing."""
    return (basic_initialize_pristine()
            and dispatch.owner_of(klass, INITIALIZE)
            == value.core_class(value.C_BASIC_OBJECT))


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


def kind_of(recv, target, mid):
    """Kernel#kind_of?/#is_a? cached per (class, module), so a promoted receiver folds it to a constant."""
    bit = B_KERNEL_KIND_OF if mid == KIND_OF_P else B_KERNEL_IS_A
    if not _cruby_owns(bit):
        return value.Q_UNDEF
    if value.is_immediate(target):
        return value.Q_UNDEF
    klass = value.class_of(recv)
    if klass == 0:
        return value.Q_UNDEF
    got = dispatch.kind_of(promote(klass), target)
    if got < 0:
        return value.Q_UNDEF
    return value.newbool(got == 1)


def sym_eqq(a, b):
    """Symbol#=== is Kernel's, which is ==, which for a Symbol compares the words."""
    if value.class_of(a) != value.core_class(value.C_SYMBOL):
        return value.Q_UNDEF
    if not _cruby_owns(B_KERNEL_EQQ) or not _sym_op(B_SYM_EQ):
        return value.Q_UNDEF
    if dispatch.lookup_core(value.core_class(value.C_SYMBOL), EQQ) is not None:
        return value.Q_UNDEF
    return value.newbool(a == b)


def responds_to(recv, sym):
    """Object#respond_to? cached per (class, symbol), so a promoted receiver folds it to a constant; a class that overrides respond_to? or respond_to_missing? answers per receiver and goes back to CRuby."""
    if (sym & value.SYMBOL_MASK) != value.SYMBOL_FLAG:
        return value.Q_UNDEF
    klass = value.class_of(recv)
    if klass == 0:
        return value.Q_UNDEF
    got = dispatch.responds(promote(klass), sym)
    if got < 0:
        return value.Q_UNDEF
    return value.newbool(got == 1)


INSTANCE_OF_P = symbols.intern('instance_of?')
CLASS_MID = symbols.intern('class')
FROZEN_P = symbols.intern('frozen?')
KEY_P = symbols.intern('key?')
HAS_KEY_P = symbols.intern('has_key?')
INCLUDE_P = symbols.intern('include?')
START_WITH_P = symbols.intern('start_with?')


def _real_class_of(recv, mid):
    """The class Kernel#class answers, when the receiver's class is no singleton and resolves mid to the pristine Kernel one; 0 otherwise."""
    if modules.kernel == 0:
        return 0
    klass = value.class_of(recv)
    if klass == 0:
        return 0
    klass = promote(klass)
    flags = raw_word(klass, value.FLAGS_WORD)
    if flags & value.T_MASK != value.T_CLASS \
            or flags & value.FL_SINGLETON != 0:
        return 0
    if dispatch.lookup(klass, mid) is not None:
        return 0
    if dispatch.owner_of(klass, mid) != modules.kernel:
        return 0
    return klass


def instance_of(recv, target):
    """Kernel#instance_of? is one class comparison; a target that is no Class or Module must raise, so it goes back to CRuby."""
    klass = _real_class_of(recv, INSTANCE_OF_P)
    if klass == 0:
        return value.Q_UNDEF
    if klass == target:
        return value.Q_TRUE
    if value.is_immediate(target):
        return value.Q_UNDEF
    t = raw_word(target, value.FLAGS_WORD) & value.T_MASK
    if t != value.T_CLASS and t != value.T_MODULE:
        return value.Q_UNDEF
    return value.Q_FALSE


def obj_class(recv):
    klass = _real_class_of(recv, CLASS_MID)
    if klass == 0:
        return value.Q_UNDEF
    return klass


def frozen_p(recv):
    """Kernel#frozen? is the FL_FREEZE bit; immediates go back to CRuby, which answers true for them."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if _real_class_of(recv, FROZEN_P) == 0:
        return value.Q_UNDEF
    return value.newbool(
        raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0)


def hash_key_p(recv, key, mid):
    """Hash#key? through the same lookup as Hash#[]: absence is exactly the Qundef a miss answers, and an error raised instead."""
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    bit = B_HASH_KEY if mid == KEY_P else B_HASH_HAS_KEY
    if not _core_op(value.C_HASH, bit, mid):
        return value.Q_UNDEF
    if _hash_key_cannot_reenter(key):
        return value.newbool(boot.hash_lookup_fast(recv, key) != value.Q_UNDEF)
    return value.newbool(boot.hash_lookup(recv, key) != value.Q_UNDEF)


def hash_aset(recv, key, val):
    """Hash#[]= in one protected call; the frozen check raises inside it."""
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    if not _core_op(value.C_HASH, B_HASH_ASET, ASET):
        return value.Q_UNDEF
    if _hash_key_cannot_reenter(key) \
            and raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE == 0:
        boot.hash_aset_fast(recv, key, val)
        return val
    boot.hash_aset(recv, key, val)
    return val


def set_include(recv, elt):
    """Set#include? of a direct core Set, which the shim checks; the guard here is only that nothing redefined it."""
    if value.is_immediate(recv) or not _cruby_owns(B_SET_INCLUDE):
        return value.Q_UNDEF
    if dispatch.lookup(promote(value.class_of(recv)), INCLUDE_P) is not None:
        return value.Q_UNDEF
    return boot.set_include(recv, elt)


def str_start_with(recv, prefix):
    """String#start_with? with one String argument: a byte compare in the shim."""
    if not value.is_plain_string(recv) \
            or not _core_op(value.C_STRING, B_STR_START_WITH, START_WITH_P):
        return value.Q_UNDEF
    return boot.str_start_with(recv, prefix)


def _owned_by_core(recv, klass_i, mid):
    """CRuby's own core method still answers mid for recv; elidable on the method version like every owner_of."""
    return dispatch.owner_of(promote(value.class_of(recv)),
                             mid) == value.core_class(klass_i)


def str_casecmp(recv, arg):
    """String#casecmp for two Strings: C only, nothing to raise."""
    if value.is_immediate(recv) or value.is_immediate(arg) \
            or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, CASECMP):
        return value.Q_UNDEF
    return boot.str_casecmp(recv, arg)


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


def str_case(recv, mid):
    """String#downcase/#upcase and bang forms; the shim takes only 7-bit Strings. A subclass goes back: the plain forms answer a plain String there."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, mid):
        return value.Q_UNDEF
    if mid == DOWNCASE:
        return boot.str_downcase(recv)
    if mid == DOWNCASE_BANG:
        return boot.str_downcase_bang(recv)
    if mid == UPCASE:
        return boot.str_upcase(recv)
    return boot.str_upcase_bang(recv)


def int_to_s(recv):
    """Integer#to_s with no base argument, for a FIXNUM receiver."""
    if not value.is_fixnum(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_INTEGER, TO_S):
        return value.Q_UNDEF
    return boot.int_to_s(recv)


def sym_to_s(recv):
    if not boot.is_symbol(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_SYMBOL, TO_S):
        return value.Q_UNDEF
    return boot.sym_to_s(recv)


def str_dup(recv):
    """String#dup on the exact class; string.c defines its own dup since 3.3."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, DUP):
        return value.Q_UNDEF
    return boot.str_dup(recv)


def ss_zero(recv, mid):
    """StringScanner's struct reads; the shim's TypedData check is the guard."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if mid == POS_MID:
        return boot.ss_pos(recv)
    if mid == EOS_P_MID:
        return boot.ss_eos_p(recv)
    return boot.ss_matched_size(recv)


def ss_set_pos(recv, arg):
    if value.is_immediate(recv):
        return value.Q_UNDEF
    return boot.ss_set_pos(recv, arg)


def ss_skip(recv, arg):
    if value.is_immediate(recv) or value.is_immediate(arg):
        return value.Q_UNDEF
    return boot.ss_skip(recv, arg)


def str_byteslice(recv, beg, length):
    if value.is_immediate(recv) or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, BYTESLICE):
        return value.Q_UNDEF
    return boot.str_byteslice2(recv, beg, length)


def str_match_p(recv, arg):
    """String#match? of a Regexp: no backref, so nothing but the search itself leaves RPython."""
    if value.is_immediate(recv) or value.is_immediate(arg) \
            or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, MATCH_P):
        return value.Q_UNDEF
    return boot.str_match_p(recv, arg)


def str_gsub2(recv, pat, rep, mid):
    """String#gsub / #gsub! with a Regexp|String pattern and a String replacement: the shim rules out a backreference escape and encoding mismatch in C."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, mid):
        return value.Q_UNDEF
    return boot.str_gsub2(recv, pat, rep, rubycall.rid(mid), mid)


def str_uminus(recv):
    """String#-@: the interned frozen copy."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, UMINUS):
        return value.Q_UNDEF
    return boot.str_uminus(recv)


def ary_pop(recv):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, POP_MID):
        return value.Q_UNDEF
    return boot.ary_pop(recv)


def ary_push_one(recv, arg):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, PUSH_MID):
        return value.Q_UNDEF
    return boot.ary_push1(recv, arg)


def ary_shift(recv):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, SHIFT_MID):
        return value.Q_UNDEF
    return boot.ary_shift(recv)


def ary_unshift1(recv, arg):
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, UNSHIFT_MID):
        return value.Q_UNDEF
    return boot.ary_unshift1(recv, arg)


def ary_flatten_bang(recv):
    """Array#flatten! for literal-Array elements only; a #to_ary-quacking non-Array element is a known corner, left untouched here."""
    if not value.is_plain_array(recv) \
            or raw_word(recv, value.FLAGS_WORD) & value.FL_FREEZE != 0:
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, FLATTEN_BANG_MID):
        return value.Q_UNDEF
    return boot.ary_flatten_bang1(recv)


def ary_hash_freeze(recv):
    """Array#freeze / Hash#freeze: OBJ_FREEZE_RAW cannot re-enter Ruby for either type."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if value.is_plain_array(recv):
        klass_i = value.C_ARRAY
    elif raw_word(recv, value.KLASS_WORD) == value.core_class(value.C_HASH):
        klass_i = value.C_HASH
    else:
        return value.Q_UNDEF
    if not _owned_by_core(recv, klass_i, FREEZE):
        return value.Q_UNDEF
    return boot.ary_hash_freeze(recv)


def hash_keys(recv):
    if value.is_immediate(recv) \
            or raw_word(recv, value.KLASS_WORD) != value.core_class(value.C_HASH):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_HASH, KEYS_MID):
        return value.Q_UNDEF
    return boot.hash_keys_fast(recv)


def str_tr(recv, frm, to):
    """String#tr of one plain byte for another; anything wider goes back."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, TR):
        return value.Q_UNDEF
    return boot.str_tr1(recv, frm, to)


def str_index(recv, arg):
    """String#index of a String needle, both 7-bit, no offset."""
    if value.is_immediate(recv) or value.is_immediate(arg) \
            or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, INDEX_MID):
        return value.Q_UNDEF
    return boot.str_index_of(recv, arg)


def str_length(recv, mid):
    """String#length/#size: character count, byte count for a 7-bit string."""
    if value.is_immediate(recv) or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, mid):
        return value.Q_UNDEF
    return boot.str_length(recv)


def ary_sub_aref(recv, idx):
    """Array#[] with an Integer on a subclass that kept Array's; rb_ary_entry handles bounds and negatives."""
    if value.is_immediate(recv) or not value.is_fixnum(idx) \
            or not boot.is_array(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, AREF):
        return value.Q_UNDEF
    return boot.ary_entry(recv, value.fix2int(idx))


def ary_sub_length(recv, mid):
    """Array#length/#size on a subclass that kept Array's."""
    if value.is_immediate(recv) or not boot.is_array(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_ARRAY, mid):
        return value.Q_UNDEF
    return value.int2fix(boot.ary_len(recv))


def str_eqq(a, b):
    """String#=== is rb_str_equal, the same function as ==."""
    if not value.is_plain_string(a) \
            or not _core_op(value.C_STRING, B_STR_EQQ, EQQ):
        return value.Q_UNDEF
    v = boot.str_eq(a, b)
    if v != value.Q_UNDEF:
        return v
    if value.is_immediate(b) \
            and dispatch.owner_of(promote(value.class_of(b)),
                                  TO_STR) == value.Q_NIL:
        return value.Q_FALSE
    return value.Q_UNDEF


def mod_eqq(a, b):
    """Module#=== is kind_of? with the operands swapped, answered from the two classes alone."""
    if value.is_immediate(a):
        return value.Q_UNDEF
    t = raw_word(a, value.FLAGS_WORD) & value.T_MASK
    if t != value.T_CLASS and t != value.T_MODULE:
        return value.Q_UNDEF
    ka = promote(value.class_of(a))
    if dispatch.owner_of(ka, EQQ) != value.core_class(value.C_MODULE) \
            or dispatch.lookup(ka, EQQ) is not None:
        return value.Q_UNDEF
    kb = value.class_of(b)
    if kb == 0:
        return value.Q_UNDEF
    got = dispatch.kind_of(promote(kb), a)
    if got < 0:
        return value.Q_UNDEF
    return value.newbool(got == 1)


def _ary_eq_false(a, b):
    """rb_ary_equal (array.c:5382) answers false for an argument that is neither an Array nor something answering to_ary; no BOP flag watches Array#==, so ask CRuby who owns it, as int_abs does."""
    if not (value.is_plain_array(a) and value.is_immediate(b)):
        return False
    # TODO: a respond_to? or respond_to_missing? that claims a to_ary the class does not define is still read as no to_ary, as in opt_not's note.
    if dispatch.owner_of(promote(value.class_of(b)), TO_ARY) != value.Q_NIL:
        return False
    klass = value.core_class(value.C_ARRAY)
    return (dispatch.owner_of(klass, EQ) == klass
            and dispatch.lookup_core(klass, EQ) is None)


def _str_eq(a, b):
    """vm_opt_str_eq's arm (vm_insnhelper.c:2540); an argument that is neither a String nor something answering to_str is false, as rb_str_equal answers it (string.c:4271)."""
    if not (value.is_plain_string(a) and _str_eq_op()):
        return value.Q_UNDEF
    v = boot.str_eq(a, b)
    if v != value.Q_UNDEF:
        return v
    # TODO: a respond_to_missing? claiming a to_str the class does not define is still read as no to_str, as in _ary_eq_false.
    if value.is_immediate(b) \
            and dispatch.owner_of(promote(value.class_of(b)),
                                  TO_STR) == value.Q_NIL:
        return value.Q_FALSE
    return value.Q_UNDEF


def eq(a, b):
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a == b)
    if _flt2(a, b, B_FLT_EQ, True):
        return value.newbool(_dbl(a) == _dbl(b))
    # `n == nil`: Integer#== hands a non-numeric to the argument's ==, which for an untouched NilClass is identity (numeric.c num_equal).
    if b == value.Q_NIL and value.is_fixnum(a) and _int_op(B_INT_EQ) \
            and identity_op(b, EQ):
        return value.Q_FALSE
    v = _str_eq(a, b)
    if v != value.Q_UNDEF:
        return v
    if identity_send(a, EQ):
        return value.newbool(a == b)
    if _ary_eq_false(a, b):
        return value.Q_FALSE
    return value.Q_UNDEF


def int_eqq(a, b):
    """Integer#=== for two Fixnums; unlike ==, === has no CRuby BOP flag."""
    if value.is_fixnum(a) and value.is_fixnum(b) and _int_owns(EQQ):
        return value.newbool(a == b)
    return value.Q_UNDEF


def int_eqq_pristine():
    return _int_owns(EQQ)


def neq(a, b):
    # BOP_NEQ is never flagged: vm_opt_neq resolves `!=` to BasicObject#!= then asks opt_equality, so Integer#== is the definition that counts.
    if _fix2(a, b, B_INT_EQ):
        return value.newbool(a != b)
    if _flt2(a, b, B_FLT_EQ, True):
        return value.newbool(_dbl(a) != _dbl(b))
    # As eq's nil arm: a Fixnum is never nil once both operators are untouched.
    if b == value.Q_NIL and value.is_fixnum(a) and _int_op(B_INT_EQ) \
            and identity_op(b, EQ):
        return value.Q_TRUE
    if value.is_plain_string(a) \
            and dispatch.owns_identity(value.core_class(value.C_STRING), NEQ):
        v = _str_eq(a, b)
        if v != value.Q_UNDEF:
            return value.newbool(v == value.Q_FALSE)
    if identity_send(a, NEQ):
        return value.newbool(a != b)
    if _ary_eq_false(a, b) \
            and dispatch.owns_identity(value.core_class(value.C_ARRAY), NEQ):
        return value.Q_TRUE
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


def int_abs(recv):
    """Integer#abs for a Fixnum; no BOP flag watches it, so ask CRuby who owns it, as identity_op does."""
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


def _int_owns(mid):
    """No BOP flag watches these, so ask CRuby who owns them, as int_abs does."""
    klass = value.core_class(value.C_INTEGER)
    return (dispatch.owner_of(klass, mid) == klass
            and dispatch.lookup_core(klass, mid) is None)


def int_uminus(recv):
    """Integer#-@ for a Fixnum; the fixnum minimum negates to a Bignum, which only CRuby builds."""
    if not value.is_fixnum(recv) or not _int_owns(UMINUS):
        return value.Q_UNDEF
    n = -value.fix2int(recv)
    if not value.fixable(n):
        return value.Q_UNDEF
    return value.int2fix(n)


def int_bitref(a, b):
    """Integer#[] for a non-negative Fixnum index; a Range or negative index (rb_int_aref, numeric.c:5001) goes back to CRuby."""
    if not (value.is_fixnum(a) and value.is_fixnum(b)) or not _int_owns(AREF):
        return value.Q_UNDEF
    s = value.fix2int(b)
    if s < 0:
        return value.Q_UNDEF
    # A fixnum is under 63 bits, so any wider index reads the sign.
    if s >= LONG_BIT - 1:
        s = LONG_BIT - 1
    return value.int2fix((value.fix2int(a) >> s) & 1)


def str_concat(a, b):
    """String#<< appending a String, or a byte to a binary String; a frozen receiver and an encoding negotiation stay with CRuby's rb_str_concat."""
    if not value.is_plain_string(a):
        return value.Q_UNDEF
    if not (value.is_plain_string(b) or value.is_fixnum(b)):
        return value.Q_UNDEF
    if not _core_op(value.C_STRING, B_STR_LTLT, LTLT):
        return value.Q_UNDEF
    v = boot.str_append(a, b)
    if v != value.Q_UNDEF or not value.is_plain_string(b):
        return v
    # The raw arm refused (encoding negotiation or a frozen receiver): still one protected call instead of a full send.
    return boot.str_push(a, b)


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
    # Bound the operand instead of shifting first: an overflowing shift is undefined in RPython.
    limit = 1 << (LONG_BIT - 2 - s)
    if n >= limit or n < -limit:
        return value.Q_UNDEF
    return value.int2fix(n << s)


def _flt_owns(mid):
    """No BOP flag watches these, so ask CRuby who owns them, as int_abs does."""
    klass = value.core_class(value.C_FLOAT)
    return (dispatch.owner_of(klass, mid) == klass
            and dispatch.lookup_core(klass, mid) is None)


def flt_to_i(recv):
    """flo_to_i (numeric.c:2562) truncates toward zero; NaN, an infinity and anything outside the fixnum range go back to CRuby, which raises FloatDomainError or builds the Bignum."""
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
    """rb_float_uminus (numeric.c:1048) is a plain IEEE negate, so 0.0 and -0.0 swap."""
    if not value.is_float(recv) or not _flt_owns(UMINUS):
        return value.Q_UNDEF
    return _from_dbl(-value.float_val(recv))


def zero_arg(recv, mid):
    if mid == CLASS_MID:
        return obj_class(recv)
    if mid == FROZEN_P:
        return frozen_p(recv)
    if mid == ABS:
        return int_abs(recv)
    if mid == TO_I:
        return flt_to_i(recv)
    if mid == TO_F:
        return to_f(recv)
    if mid == NAME:
        return sym_name(recv)
    if mid == TO_S:
        v = str_to_s(recv)
        if v != value.Q_UNDEF:
            return v
        v = sym_to_s(recv)
        if v != value.Q_UNDEF:
            return v
        return int_to_s(recv)
    if mid == UMINUS:
        v = flt_uminus(recv)
        if v != value.Q_UNDEF:
            return v
        v = int_uminus(recv)
        if v != value.Q_UNDEF:
            return v
        return str_uminus(recv)
    if mid == POP_MID:
        return ary_pop(recv)
    if mid == SHIFT_MID:
        return ary_shift(recv)
    if mid == FLATTEN_BANG_MID:
        return ary_flatten_bang(recv)
    if mid == FREEZE:
        return ary_hash_freeze(recv)
    if mid == KEYS_MID:
        return hash_keys(recv)
    if mid == EMPTY_P:
        return empty_p(recv)
    if mid == POS_MID or mid == EOS_P_MID or mid == MATCHED_SIZE:
        return ss_zero(recv, mid)
    if mid == DOWNCASE or mid == DOWNCASE_BANG \
            or mid == UPCASE or mid == UPCASE_BANG:
        return str_case(recv, mid)
    if mid == DUP:
        return str_dup(recv)
    if mid == LENGTH or mid == SIZE:
        v = ary_sub_length(recv, mid)
        if v != value.Q_UNDEF:
            return v
        return str_length(recv, mid)
    return range_part(recv, mid)


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
    """Array[Fixnum] reads the elements in place; a Hash goes straight to the lookup."""
    v = hash_aref(recv, idx)
    if v != value.Q_UNDEF:
        return v
    if value.is_plain_array(recv) and value.is_fixnum(idx) \
            and _ary_op(B_ARY_AREF):
        i = value.fix2int(idx)
        n = value.ary_len(recv)
        if i < 0:
            i += n
        if i >= 0 and i < n:
            return value.ary_at(recv, i)
        return value.Q_NIL
    return int_bitref(recv, idx)


def aset(recv, idx, val):
    """A store inside a writable Array goes in place; growth, sharing and FrozenError stay with rb_ary_store."""
    if value.is_plain_array(recv) and value.is_fixnum(idx) \
            and _ary_op(B_ARY_ASET):
        immediate = value.is_immediate(val)
        if immediate or dispatch.barrier.direct:
            n = value.ary_len(recv)
            i = value.fix2int(idx)
            if i < 0:
                i += n
            if i >= 0 and i < n and value.ary_writable(recv):
                value.ary_set(recv, i, val)
                if not immediate:
                    boot.obj_written(recv, val)
                return val
        rubycall.ary_store(recv, value.fix2int(idx), val)
        return val
    v = hash_aset(recv, idx, val)
    if v != value.Q_UNDEF:
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
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if boot.is_hash(recv) and _owned_by_core(recv, value.C_HASH, EMPTY_P):
        return boot.hash_empty_p(recv)
    if boot.is_string(recv) and _owned_by_core(recv, value.C_STRING, EMPTY_P):
        return boot.str_empty_p(recv)
    return value.Q_UNDEF


def ary_new_pristine(recv):
    """A direct Array whose Array.new and Array#initialize are still CRuby's own, on both sides, so RPyYARV may build the array itself."""
    return (recv == value.core_class(value.C_ARRAY)
            and _cruby_owns(B_ARY_NEW) and _cruby_owns(B_ARY_INITIALIZE)
            and dispatch.lookup_core(recv, INITIALIZE) is None)


def nil_p(recv):
    """vm_opt_nil_p's first arm, plus the false a receiver whose class still resolves nil? to Kernel's owes; the owner is the pristine Kernel, so redefining it anywhere in the chain is seen."""
    if recv == value.Q_NIL:
        if _cruby_owns(B_NIL_NIL_P) \
                and dispatch.lookup_core(value.core_class(value.C_NILCLASS),
                                         NIL_P) is None:
            return value.Q_TRUE
        return value.Q_UNDEF
    klass = value.class_of(recv)
    if klass == 0 or modules.kernel == 0 or not _cruby_owns(B_KERNEL_NIL_P):
        return value.Q_UNDEF
    klass = promote(klass)
    # The registry too: a `nil?` RPyYARV defined in a module is invisible to CRuby's owner.
    if dispatch.lookup(klass, NIL_P) is not None:
        return value.Q_UNDEF
    if dispatch.owner_of(klass, NIL_P) != modules.kernel:
        return value.Q_UNDEF
    return value.Q_FALSE


def str_freeze_pristine():
    """String#freeze still CRuby's own, so opt_str_freeze may push the literal."""
    return (_cruby_owns(B_STR_FREEZE)
            and dispatch.lookup_core(value.core_class(value.C_STRING),
                                     FREEZE) is None)


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
            value.ARY_HEAP_PTR_WORD, value.ARY_EMBED_WORD,
            value.ARY_SHARED_FLAG, value.ARY_SHARED_ROOT_FLAG,
            value.ARY_HEAP_CAPA_WORD, value.T_ARRAY]
    return got == want
