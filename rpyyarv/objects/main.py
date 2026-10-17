"""The toplevel self: an ordinary Object, as in CRuby."""

from rpyyarv import classlib
from rpyyarv import kernel
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import (w_array_class, w_class_class, w_object_class,
                           w_string_class)
from rpyyarv.objects import array as arraylib
from rpyyarv.objects import string as stringlib

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
stringlib.install(w_string_class)
arraylib.install(w_array_class)

w_main = W_Main()
