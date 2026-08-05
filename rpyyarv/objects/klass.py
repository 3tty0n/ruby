"""Classes: the method tables that method lookup walks."""

from methods import MethodTable
from objects.base import W_Root
from rlib import elidable


class VersionTag(object):
    pass


class W_Class(W_Root):
    _immutable_fields_ = ['name', 'w_superclass', 'version?']

    def __init__(self, name, w_superclass=None):
        self.name = name
        self.w_superclass = w_superclass
        self.methods = MethodTable()
        self.subclasses_w = []
        self.version = VersionTag()
        if w_superclass is not None:
            w_superclass.subclasses_w.append(self)

    def add_method(self, mid, w_method):
        self.methods.define(mid, w_method)
        self.method_table_changed()

    def method_table_changed(self):
        self.version = VersionTag()
        for w_subclass in self.subclasses_w:
            w_subclass.method_table_changed()

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
w_integer_class = W_Class('Integer', w_object_class)
w_string_class = W_Class('String', w_object_class)
w_array_class = W_Class('Array', w_object_class)
w_nil_class = W_Class('NilClass', w_object_class)
w_true_class = W_Class('TrueClass', w_object_class)
w_false_class = W_Class('FalseClass', w_object_class)
