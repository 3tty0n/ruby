from rpyyarv import symbols
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_regexp_class
from rpyyarv.objects.transparent import newbool

class W_Regexp(W_Root):
    def __init__(self, pattern):
        self.pattern = pattern

    def getclass(self):
        return w_regexp_class

    def repr(self):
        return '/%s/' % self.pattern


class W_RegexpEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Regexp)
        w_other = args_w[0]
        return newbool(isinstance(w_other, W_Regexp)
                       and w_other.pattern == w_recv.pattern)


def install(w_class):
    mid = symbols.intern('==')
    w_class.add_method(mid, W_RegexpEqual(mid, 1))
