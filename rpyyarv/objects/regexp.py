from objects.base import W_Root
from objects.klass import w_regexp_class

class W_Regexp(W_Root):
    def __init__(self, pattern):
        self.pattern = pattern

    def getclass(self):
        return w_regexp_class

    def repr(self):
        return '/%s/' % self.pattern