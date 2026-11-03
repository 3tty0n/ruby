"""Classes: the method tables that method lookup walks."""

from rpyyarv import symbols
from rpyyarv.methods import MethodTable
from rpyyarv.objects.base import W_Root
from rpyyarv.rlib import elidable, unroll_safe

# Methods of a built-in class that the interpreter computes itself until
# Ruby code redefines them, as CRuby's BOP flags
BOP_PLUS = 1 << 0
BOP_MINUS = 1 << 1
BOP_MULT = 1 << 2
BOP_DIV = 1 << 3
BOP_MOD = 1 << 4
BOP_LT = 1 << 5
BOP_GT = 1 << 6
BOP_LE = 1 << 7
BOP_GE = 1 << 8
BOP_EQ = 1 << 9
BOP_NEQ = 1 << 10
BOP_AREF = 1 << 11
BOP_ASET = 1 << 12
BOP_LENGTH = 1 << 13
BOP_SIZE = 1 << 14
BOP_EMPTY_P = 1 << 15

_BOP_BITS = {}
for _name, _bit in [('+', BOP_PLUS), ('-', BOP_MINUS), ('*', BOP_MULT),
                    ('/', BOP_DIV), ('%', BOP_MOD), ('<', BOP_LT),
                    ('>', BOP_GT), ('<=', BOP_LE), ('>=', BOP_GE),
                    ('==', BOP_EQ), ('!=', BOP_NEQ), ('[]', BOP_AREF),
                    ('[]=', BOP_ASET), ('length', BOP_LENGTH),
                    ('size', BOP_SIZE), ('empty?', BOP_EMPTY_P)]:
    _BOP_BITS[symbols.intern(_name)] = _bit


class VersionTag(object):
    pass


class W_Class(W_Root):
    _immutable_fields_ = ['name', 'w_superclass', 'builtin', 'version?',
                          'const_version?', 'w_singleton?', 'redefined?']

    def __init__(self, name, w_superclass=None, builtin=False):
        self.name = name
        self.w_superclass = w_superclass
        self.builtin = builtin
        self.methods = MethodTable()
        self.subclasses_w = []
        self.version = VersionTag()
        self.constants_w = {}
        self.const_version = VersionTag()
        self.w_singleton = None
        self.redefined = 0
        if w_superclass is not None:
            w_superclass.subclasses_w.append(self)

    def getclass(self):
        return w_class_class

    def lookup_class(self):
        return self.singleton_class()

    def singleton_class(self):
        # Made on first use; its superclass is the superclass's own, so class
        # methods are inherited, and Object's leads on to Class
        if self.w_singleton is None:
            if self.w_superclass is None:
                w_super = w_class_class
            else:
                w_super = self.w_superclass.singleton_class()
            self.w_singleton = W_Class('#<Class:%s>' % self.name, w_super)
        return self.w_singleton

    def method_owner(self):
        return self

    def add_user_method(self, mid, w_method):
        if self.builtin and mid in _BOP_BITS:
            self.redefined |= _BOP_BITS[mid]
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

    @unroll_safe
    def find_const_in_ancestors(self, mid, exclude_object):
        w_class = self
        while w_class is not None:
            if exclude_object and w_class is w_object_class:
                return None
            w_value = w_class.find_const(mid)
            if w_value is not None:
                return w_value
            w_class = w_class.w_superclass
        return None

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


w_object_class = W_Class('Object', None, True)
# Ruby interposes Module between Class and Object; it owns nothing we call yet.
w_class_class = W_Class('Class', w_object_class, True)
w_numeric_class = W_Class('Numeric', w_object_class, True)
w_integer_class = W_Class('Integer', w_numeric_class, True)
w_float_class = W_Class('Float', w_numeric_class, True)
w_string_class = W_Class('String', w_object_class, True)
w_symbol_class = W_Class('Symbol', w_object_class, True)
w_regexp_class = W_Class('Regexp', w_object_class, True)
w_array_class = W_Class('Array', w_object_class, True)
w_hash_class = W_Class('Hash', w_object_class, True)
w_range_class = W_Class('Range', w_object_class, True)
w_enumerator_class = W_Class('Enumerator', w_object_class, True)
w_nil_class = W_Class('NilClass', w_object_class, True)
w_true_class = W_Class('TrueClass', w_object_class, True)
w_false_class = W_Class('FalseClass', w_object_class, True)
