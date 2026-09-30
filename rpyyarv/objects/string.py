import symbols
from methods import W_CFunc
from objects.array import W_Array
from objects.base import W_Root
from objects.klass import w_string_class
from objects.regexp import W_Regexp
from objects.transparent import W_Fixnum
from error import UnsupportedOperation

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

class W_ToI(W_CFunc):
    def call(self, w_recv, args_w):
        assert isinstance(w_recv, W_String)
        try:
            return W_Fixnum(int(w_recv.strval))
        except ValueError:
            raise UnsupportedOperation(
                "to_i on %s: RPyYARV only supports a plain integer string, "
                "not Ruby's full parsing" % w_recv.repr())

class W_Split(W_CFunc):
    def call(self, w_recv, args_w):
        assert isinstance(w_recv, W_String)
        w_pattern = args_w[0]
        if isinstance(w_pattern, W_Regexp) and w_pattern.pattern == '':
            return W_Array([W_String(c) for c in w_recv.strval])
        raise UnsupportedOperation(
            "split on %s: RPyYARV only supports split(//) so far"
            % w_pattern.repr())

def install(w_class):
    mid = symbols.intern('to_i')
    w_class.add_method(mid, W_ToI(mid, 0))  # arity=0
    split_id = symbols.intern('split')
    w_class.add_method(split_id, W_Split(split_id, 1))  # arity=1: 0 arguments and 2 arguments(with limit) are not supported yet