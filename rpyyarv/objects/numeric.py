from rpyyarv import symbols
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.transparent import newint, w_false, w_nil, w_true


class W_Self(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return w_recv


class W_Const(W_CFunc):
    _immutable_fields_ = ['w_value']

    def __init__(self, mid, w_value):
        W_CFunc.__init__(self, mid, 0)
        self.w_value = w_value

    def call(self, w_recv, args_w, w_block):
        return self.w_value


def _add_self(w_class, name):
    mid = symbols.intern(name)
    w_class.add_method(mid, W_Self(mid, 0))


def _add_const(w_class, name, w_value):
    mid = symbols.intern(name)
    w_class.add_method(mid, W_Const(mid, w_value))


def install(w_class):
    _add_const(w_class, 'real?', w_true)
    _add_self(w_class, 'real')
    _add_const(w_class, 'imag', newint(0))
    _add_self(w_class, 'conj')
    _add_const(w_class, 'integer?', w_false)
    _add_const(w_class, 'finite?', w_true)
    _add_const(w_class, 'infinite?', w_nil)


def install_integer(w_class):
    _add_const(w_class, 'integer?', w_true)
    _add_self(w_class, 'numerator')
    _add_const(w_class, 'denominator', newint(1))
