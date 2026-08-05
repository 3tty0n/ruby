"""The toplevel self: an object whose singleton class is where `def` lands."""

import kernel
from objects.base import W_Root
from objects.klass import W_Class, w_object_class


class W_Main(W_Root):
    def __init__(self):
        self.w_class = W_Class('#<Class:main>', w_object_class)

    def getclass(self):
        return self.w_class

    def define_method(self, mid, w_method):
        self.w_class.add_method(mid, w_method)

    def repr(self):
        return 'main'


kernel.install(w_object_class)

w_main = W_Main()
