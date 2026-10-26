import math

from rpyyarv import symbols
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_float_class
from rpyyarv.objects.numeric import W_Self
from rpyyarv.objects.transparent import newbool, newint, w_nil
from rpyyarv.rlib import float_repr

DBL_DIG = 15


class W_Float(W_Root):
    _immutable_fields_ = ['floatval']

    def __init__(self, floatval):
        self.floatval = floatval

    def getclass(self):
        return w_float_class

    def float_w(self):
        return self.floatval

    def to_s_str(self):
        return float_to_s(self.floatval)

    def repr(self):
        return float_to_s(self.floatval)


def float_to_s(x):
    """CRuby's flo_to_s in numeric.c."""
    if math.isinf(x):
        if x > 0.0:
            return 'Infinity'
        return '-Infinity'
    if math.isnan(x):
        return 'NaN'
    sign = ''
    if math.copysign(1.0, x) < 0.0:
        sign = '-'
        x = -x
    if x == 0.0:
        return sign + '0.0'

    s = float_repr(x)
    exp = 0
    epos = s.find('e')
    if epos >= 0:
        exp = int(s[epos + 1:])
        s = s[:epos]
    dot = s.find('.')
    if dot < 0:
        digits = s
        decpt = len(s)
    else:
        digits = s[:dot] + s[dot + 1:]
        decpt = dot
    stripped = digits.lstrip('0')
    decpt = decpt + exp - (len(digits) - len(stripped))
    digits = stripped.rstrip('0')

    digs = len(digits)
    if decpt > 0:
        if decpt < digs:
            return sign + digits[:decpt] + '.' + digits[decpt:]
        if decpt <= DBL_DIG:
            return sign + digits + '0' * (decpt - digs) + '.0'
    elif decpt > -4:
        return sign + '0.' + '0' * -decpt + digits
    frac = digits[1:]
    if not frac:
        frac = '0'
    e = decpt - 1
    esign = '+'
    if e < 0:
        esign = '-'
        e = -e
    estr = str(e)
    if len(estr) < 2:
        estr = '0' + estr
    return sign + digits[0] + '.' + frac + 'e' + esign + estr


def _floatval(w_recv):
    assert isinstance(w_recv, W_Float)
    return w_recv.floatval


class W_Abs(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return W_Float(math.fabs(_floatval(w_recv)))


class W_Neg(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return W_Float(-_floatval(w_recv))


class W_IsZero(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return newbool(_floatval(w_recv) == 0.0)


class W_IsNegative(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return newbool(_floatval(w_recv) < 0.0)


class W_IsPositive(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return newbool(_floatval(w_recv) > 0.0)


class W_IsFinite(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        x = _floatval(w_recv)
        return newbool(not (math.isinf(x) or math.isnan(x)))


class W_IsInfinite(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        x = _floatval(w_recv)
        if not math.isinf(x):
            return w_nil
        if x > 0.0:
            return newint(1)
        return newint(-1)


def install(w_class):
    for name, cls in [('to_f', W_Self), ('abs', W_Abs), ('magnitude', W_Abs),
                      ('-@', W_Neg), ('zero?', W_IsZero),
                      ('negative?', W_IsNegative), ('positive?', W_IsPositive),
                      ('finite?', W_IsFinite), ('infinite?', W_IsInfinite)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, 0))
