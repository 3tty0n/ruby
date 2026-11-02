"""The toplevel self: an ordinary Object, as in CRuby."""

from rpyyarv import classlib
from rpyyarv import symbols
from rpyyarv import kernel
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import (W_Class, w_array_class, w_class_class,
                                   w_enumerator_class, w_false_class,
                                   w_float_class, w_hash_class,
                                   w_integer_class, w_nil_class,
                                   w_numeric_class, w_object_class,
                                   w_range_class, w_regexp_class,
                                   w_string_class, w_symbol_class,
                                   w_true_class)
from rpyyarv.objects import array as arraylib
from rpyyarv.objects import enumerator as enumeratorlib
from rpyyarv.objects import float as floatlib
from rpyyarv.objects import hash as hashlib
from rpyyarv.objects import numeric as numericlib
from rpyyarv.objects import range as rangelib
from rpyyarv.objects import regexp as regexplib
from rpyyarv.objects import string as stringlib
from rpyyarv.objects.transparent import w_nil

# CRuby gives main a singleton class with its own to_s, so a toplevel
# `def to_s` (which lands on Object) does not change how main prints.
w_main_class = W_Class('Object', w_object_class)


class W_Main(W_Root):
    def __init__(self):
        self.ivars_w = {}

    def getclass(self):
        return w_main_class

    def get_ivar(self, mid):
        return self.ivars_w.get(mid, w_nil)

    def set_ivar(self, mid, w_value):
        self.ivars_w[mid] = w_value

    # CRuby defines a toplevel `def` as a private method on Object, not on a
    # singleton class of main.
    def defines_private(self):
        return True

    def method_owner(self):
        return w_object_class

    def to_s_str(self):
        return 'main'

    def repr(self):
        return 'main'


kernel.install(w_object_class)
kernel.install_to_s(w_main_class)
for _w_class in (w_integer_class, w_float_class, w_nil_class, w_true_class,
                 w_false_class, w_string_class, w_symbol_class):
    kernel.install_to_s(_w_class)
classlib.install(w_class_class)
classlib.install_object(w_object_class)
stringlib.install(w_string_class)
arraylib.install(w_array_class)
hashlib.install(w_hash_class)
rangelib.install(w_range_class)
regexplib.install(w_regexp_class)
enumeratorlib.install(w_enumerator_class)
numericlib.install(w_numeric_class)
numericlib.install_integer(w_integer_class)
floatlib.install(w_float_class)
numericlib.install_operators(w_integer_class)
numericlib.install_operators(w_float_class)

for _w_class in (w_object_class, w_class_class, w_numeric_class,
                 w_integer_class, w_float_class, w_string_class,
                 w_symbol_class, w_array_class, w_hash_class, w_range_class,
                 w_enumerator_class, w_regexp_class, w_nil_class,
                 w_true_class, w_false_class):
    w_object_class.set_const(symbols.intern(_w_class.name), _w_class)

w_main = W_Main()
