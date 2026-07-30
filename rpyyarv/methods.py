"""Methods and method tables.
"""

import symbols
from error import UnsupportedOperation
from objects.base import W_Root


class W_Method(W_Root):
    def __init__(self, mid):
        self.mid = mid

    def repr(self):
        return '<W_Method %s>' % symbols.name_of(self.mid)


class W_ISeqMethod(W_Method):
    def __init__(self, mid, w_iseq):
        W_Method.__init__(self, mid)
        self.w_iseq = w_iseq

    def repr(self):
        return '<W_ISeqMethod %s>' % self.w_iseq.name


class W_CFunc(W_Method):
    def __init__(self, mid, arity):
        W_Method.__init__(self, mid)
        self.arity = arity      # -1 takes any number of arguments

    def call(self, w_recv, args_w):
        raise UnsupportedOperation("'%s' has no body"
                                   % symbols.name_of(self.mid))


class MethodTable(object):
    def __init__(self):
        self.methods = {}

    def define(self, mid, w_method):
        self.methods[mid] = w_method

    def lookup(self, mid):
        return self.methods.get(mid, None)
