"""The toplevel self: an ordinary Object, as in CRuby."""

import classlib
import kernel
from objects.base import W_Root
from objects.klass import w_class_class, w_object_class


class W_Main(W_Root):
    def getclass(self):
        return w_object_class

    # CRuby defines a toplevel `def` as a private method on Object, not on a
    # singleton class of main.
    def defines_private(self):
        return True

    def define_method(self, mid, w_method):
        w_object_class.add_method(mid, w_method)

    def repr(self):
        return 'main'


kernel.install(w_object_class)
classlib.install(w_class_class)

w_main = W_Main()
