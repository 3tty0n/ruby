from objects.base import W_Root
from objects.klass import (w_false_class, w_integer_class, w_nil_class,
                           w_true_class)
from rlib import elidable

class W_Fixnum(W_Root):
    _immutable_fields_ = ['intval']

    def __init__(self, intval):
        self.intval = intval

    @elidable
    def get_intval(self):
        return self.intval

    def getclass(self):
        return w_integer_class

    def int_w(self):
        return self.intval

    def to_s_str(self):
        return str(self.intval)

    def repr(self):
        return str(self.intval)


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
