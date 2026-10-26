"""The toplevel self: an ordinary Object, as in CRuby."""

from rpyyarv import classlib
from rpyyarv import kernel
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import (W_Class, w_array_class, w_class_class,
                                   w_false_class, w_float_class,
                                   w_integer_class, w_nil_class,
                                   w_object_class, w_string_class,
                                   w_true_class)
from rpyyarv.objects import array as arraylib
from rpyyarv.objects import string as stringlib

# CRuby gives main a singleton class with its own to_s, so a toplevel
# `def to_s` (which lands on Object) does not change how main prints.
w_main_class = W_Class('Object', w_object_class)


class W_Main(W_Root):
    def getclass(self):
        return w_main_class

    # CRuby defines a toplevel `def` as a private method on Object, not on a
    # singleton class of main.
    def defines_private(self):
        return True

    def define_method(self, mid, w_method):
        w_object_class.add_method(mid, w_method)

    def to_s_str(self):
        return 'main'

    def repr(self):
        return 'main'


kernel.install(w_object_class)
kernel.install_to_s(w_main_class)
for _w_class in (w_integer_class, w_float_class, w_nil_class, w_true_class,
                 w_false_class, w_string_class):
    kernel.install_to_s(_w_class)
classlib.install(w_class_class)
stringlib.install(w_string_class)
arraylib.install(w_array_class)

w_main = W_Main()
