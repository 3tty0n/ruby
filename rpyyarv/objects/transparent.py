from rpyyarv.error import UnsupportedOperation
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import (w_false_class, w_integer_class,
                                   w_nil_class, w_true_class)
from rpyyarv.objects.symbol import W_Symbol
from rpyyarv.rlib import (UnboxedValue, elidable, rbigint,
                          tagged_ints_enabled)


class W_Integer(W_Root):
    __slots__ = ()

    @elidable
    def get_intval(self):
        return self.int_w()

    def getclass(self):
        return w_integer_class

    def float_w(self):
        return float(self.int_w())

    def to_s_str(self):
        return str(self.int_w())

    def repr(self):
        return str(self.int_w())


class W_Fixnum(W_Integer):
    _immutable_fields_ = ['intval']

    def __init__(self, intval):
        self.intval = intval

    def int_w(self):
        return self.intval


class W_SmallFixnum(W_Integer, UnboxedValue):
    # An immediate word under translation.taggedpointers.
    __slots__ = 'intval'
    _immutable_fields_ = ['intval']

    def int_w(self):
        return self.intval


def newint(value):
    if not tagged_ints_enabled():
        return W_Fixnum(value)
    try:
        return W_SmallFixnum(value)
    except OverflowError:
        return W_Fixnum(value)


INF = float('inf')


# An Integer beyond 64 bits. int_w() refuses it, so every place that takes
# an Integer as a machine word stops instead of using a wrong value.
class W_Bignum(W_Integer):
    _immutable_fields_ = ['big']

    def __init__(self, big):
        self.big = big

    def int_w(self):
        raise UnsupportedOperation('the Bignum %s is not supported here yet'
                                   % self.big.str())

    def float_w(self):
        try:
            return self.big.tofloat()
        except OverflowError:
            if self.big.lt(rbigint.fromint(0)):
                return -INF
            return INF

    def to_s_str(self):
        return self.big.str()

    def repr(self):
        return self.big.str()


def newbig(big):
    try:
        return newint(big.toint())
    except OverflowError:
        return W_Bignum(big)


def bigint_of(w_int):
    if isinstance(w_int, W_Bignum):
        return w_int.big
    return rbigint.fromint(w_int.int_w())


class W_Nil(W_Root):
    def getclass(self):
        return w_nil_class

    def is_true(self):
        return False

    def to_s_str(self):
        return ''

    def repr(self):
        return 'nil'


class W_True(W_Root):
    def getclass(self):
        return w_true_class

    def to_s_str(self):
        return 'true'

    def repr(self):
        return 'true'


class W_False(W_Root):
    def getclass(self):
        return w_false_class

    def is_true(self):
        return False

    def to_s_str(self):
        return 'false'

    def repr(self):
        return 'false'


w_nil = W_Nil()
w_true = W_True()
w_false = W_False()


def newbool(flag):
    if flag:
        return w_true
    return w_false


def describe_operand(w_x):
    if (w_x is w_nil or w_x is w_true or w_x is w_false
            or isinstance(w_x, W_Symbol)):
        return w_x.repr()
    return w_x.getclass().name


def describe_conversion(w_x):
    if w_x is w_nil or w_x is w_true or w_x is w_false:
        return w_x.repr()
    return w_x.getclass().name
