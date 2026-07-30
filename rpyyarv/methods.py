"""Methods and method tables.

The only table so far is the one W_Main carries; per-class tables arrive by
giving other objects a table and making lookup() walk a superclass chain.
"""

from objects.base import W_Root


class W_Method(W_Root):
    def __init__(self, mid, w_iseq):
        self.mid = mid
        self.w_iseq = w_iseq

    def repr(self):
        return '<W_Method %s>' % self.w_iseq.name


class MethodTable(object):
    def __init__(self):
        self.methods = {}

    def define(self, mid, w_method):
        self.methods[mid] = w_method

    def lookup(self, mid):
        return self.methods.get(mid, None)
