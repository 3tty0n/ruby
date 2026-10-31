"""Class#new: allocate an instance, then run the class's initialize."""

from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.instance import W_Object
from rpyyarv.objects.klass import W_Class, w_object_class
from rpyyarv.objects.transparent import w_nil

INITIALIZE = symbols.intern('initialize')


def allocate(w_class):
    # A built-in class other than Object needs its own kind of object
    if w_class.builtin and w_class is not w_object_class:
        raise UnsupportedOperation('%s.new is not supported yet'
                                   % w_class.name)
    return W_Object(w_class)


class W_New(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Class)       # `new` lives only on Class
        w_obj = allocate(w_recv)
        interp.call_method(w_recv.find_method(INITIALIZE), w_obj, args_w,
                           w_block)
        return w_obj


class W_Initialize(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return w_nil


def install(w_class):
    mid = symbols.intern('new')
    w_class.add_method(mid, W_New(mid, -1))


def install_object(w_class):
    w_class.add_method(INITIALIZE, W_Initialize(INITIALIZE, 0, True))
