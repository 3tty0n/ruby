from objects.base import W_Root


class W_Fixnum(W_Root):
    def __init__(self, intval):
        self.intval = intval

    def int_w(self):
        return self.intval

    def to_s_str(self):
        return str(self.intval)

    def repr(self):
        return str(self.intval)


class W_Nil(W_Root):
    def is_true(self):
        return False

    def to_s_str(self):
        return ''

    def repr(self):
        return 'nil'


class W_True(W_Root):
    def to_s_str(self):
        return 'true'

    def repr(self):
        return 'true'


class W_False(W_Root):
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
