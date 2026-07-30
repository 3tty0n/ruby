"""The toplevel self, standing in for main, its singleton class and Object."""

import kernel
from methods import MethodTable
from objects.base import W_Root


class W_Main(W_Root):
    def __init__(self):
        self.methods = MethodTable()
        kernel.install(self)

    def lookup_method(self, mid):
        w_method = self.methods.lookup(mid)
        if w_method is None:
            raise self.no_method_error(mid)
        return w_method

    def define_method(self, mid, w_method):
        self.methods.define(mid, w_method)

    def repr(self):
        return 'main'


w_main = W_Main()
