"""The toplevel self: one object standing in for CRuby's main, its singleton
class and Object, so a toplevel `def` and a `putself` call meet in one table.
"""

from methods import MethodTable
from objects.base import W_Root


class W_Main(W_Root):
    def __init__(self):
        self.methods = MethodTable()

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
