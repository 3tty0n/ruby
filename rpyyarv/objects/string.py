from objects.base import W_Root
from objects.klass import w_string_class


class W_String(W_Root):
    # Immutable: nothing mutates a string yet, so frozen, chilled and
    # ordinary literals are all the same object here.
    def __init__(self, strval):
        self.strval = strval

    def getclass(self):
        return w_string_class

    def str_w(self):
        return self.strval

    def to_s_str(self):
        return self.strval

    def repr(self):
        return '"%s"' % self.strval
