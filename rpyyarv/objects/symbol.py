from rpyyarv import symbols
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_symbol_class


class W_Symbol(W_Root):
    _immutable_fields_ = ['mid']

    def __init__(self, mid):
        self.mid = mid

    def getclass(self):
        return w_symbol_class

    def to_s_str(self):
        return symbols.name_of(self.mid)

    def repr(self):
        return ':' + symbols.name_of(self.mid)


# One object per name, as in CRuby, so :a in two ISeqs is the same object
_symbols_w = {}


def newsymbol(mid):
    if mid in _symbols_w:
        return _symbols_w[mid]
    w_sym = W_Symbol(mid)
    _symbols_w[mid] = w_sym
    return w_sym
