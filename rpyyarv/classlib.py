"""Class#new: allocate an instance, then run the class's initialize."""

from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from objects.instance import W_Object
from objects.klass import W_Class

INITIALIZE = symbols.intern('initialize')


class W_New(W_CFunc):
    def call(self, w_recv, args_w):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Class)       # `new` lives only on Class
        w_obj = W_Object(w_recv)
        w_init = w_recv.find_method(INITIALIZE)
        if w_init is not None:
            interp.call_method(w_init, w_obj, args_w)
        elif len(args_w) != 0:
            raise UnsupportedOperation(
                "wrong number of arguments to 'new' (given %d, expected 0)"
                % len(args_w))
        return w_obj


def install(w_class):
    mid = symbols.intern('new')
    w_class.add_method(mid, W_New(mid, -1))
