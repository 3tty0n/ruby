"""Classes: the method tables that method lookup walks."""

from rpyyarv.methods import MethodTable
from rpyyarv.objects.base import W_Root
from rpyyarv.rlib import elidable


class VersionTag(object):
    pass


class W_Class(W_Root):
    _immutable_fields_ = ['name', 'w_superclass', 'version?', 'const_version?']

    def __init__(self, name, w_superclass=None):
        self.name = name
        self.w_superclass = w_superclass
        self.methods = MethodTable()
        self.subclasses_w = []
        self.version = VersionTag()
        self.constants_w = {}
        self.const_version = VersionTag()
        if w_superclass is not None:
            w_superclass.subclasses_w.append(self)

    def getclass(self):
        return w_class_class

    def define_method(self, mid, w_method):
        self.add_method(mid, w_method)

    def add_method(self, mid, w_method):
        self.methods.define(mid, w_method)
        self.method_table_changed()

    def method_table_changed(self):
        self.version = VersionTag()
        for w_subclass in self.subclasses_w:
            w_subclass.method_table_changed()

    def set_const(self, mid, w_value):
        self.constants_w[mid] = w_value
        self.const_version = VersionTag()

    def find_const(self, mid):
        return self._find_const(mid, self.const_version)

    @elidable
    def _find_const(self, mid, version):
        return self.constants_w.get(mid, None)

    def to_s_str(self):
        return self.name

    def find_method(self, mid):
        return self._find_in_ancestors(mid, self.version)

    @elidable
    def _find_in_ancestors(self, mid, version):
        # version is never read: it is the key that lets this be elidable, and
        # method_table_changed() replaces it whenever an answer would change.
        w_class = self
        while w_class is not None:
            w_method = w_class.methods.lookup(mid)
            if w_method is not None:
                return w_method
            w_class = w_class.w_superclass
        return None

    def repr(self):
        return self.name


w_object_class = W_Class('Object')
# Ruby interposes Module between Class and Object; it owns nothing we call yet.
w_class_class = W_Class('Class', w_object_class)
w_numeric_class = W_Class('Numeric', w_object_class)
w_integer_class = W_Class('Integer', w_numeric_class)
w_float_class = W_Class('Float', w_numeric_class)
w_string_class = W_Class('String', w_object_class)
w_symbol_class = W_Class('Symbol', w_object_class)
w_regexp_class = W_Class('Regexp', w_object_class)
w_array_class = W_Class('Array', w_object_class)
w_nil_class = W_Class('NilClass', w_object_class)
w_true_class = W_Class('TrueClass', w_object_class)
w_false_class = W_Class('FalseClass', w_object_class)
