import math

from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.float import W_Float
from rpyyarv.objects.klass import w_integer_class
from rpyyarv.objects.numeric import W_ToF
from rpyyarv.objects.transparent import W_Integer, describe_conversion

NAN = float('nan')
TO_F = symbols.intern('to_f')


def _get_double(w_x, name):
    if isinstance(w_x, W_Float):
        return w_x.floatval
    if isinstance(w_x, W_Integer):
        if not isinstance(w_integer_class.find_method(TO_F), W_ToF):
            raise UnsupportedOperation(
                'Math.%s after redefining Integer#to_f is not supported yet'
                % name)
        return w_x.float_w()
    raise UnsupportedOperation("can't convert %s into Float"
                               % describe_conversion(w_x))


class W_Sqrt(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        x = _get_double(args_w[0], 'sqrt')
        if x < 0.0:
            raise UnsupportedOperation(
                'Numerical argument is out of domain - sqrt')
        if x == 0.0:
            return W_Float(0.0)
        return W_Float(math.sqrt(x))


# C's sin and cos return NaN for an infinity, where math.sin and math.cos raise
class W_Sin(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        x = _get_double(args_w[0], 'sin')
        if math.isinf(x):
            return W_Float(NAN)
        return W_Float(math.sin(x))


class W_Cos(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        x = _get_double(args_w[0], 'cos')
        if math.isinf(x):
            return W_Float(NAN)
        return W_Float(math.cos(x))


def install(w_module):
    w_single = w_module.singleton_class()
    for name, cls in [('sqrt', W_Sqrt), ('sin', W_Sin), ('cos', W_Cos)]:
        mid = symbols.intern(name)
        w_single.add_method(mid, cls(mid, 1))
    w_module.set_const(symbols.intern('PI'), W_Float(math.pi))
