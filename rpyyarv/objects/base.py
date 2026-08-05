import symbols
from error import UnsupportedOperation
from rlib import promote


class W_Root(object):
    # Only nil and false are falsy in Ruby.
    def is_true(self):
        return True

    def int_w(self):
        raise UnsupportedOperation('not an integer')

    def str_w(self):
        raise UnsupportedOperation('not a string')

    def to_s_str(self):
        raise UnsupportedOperation('no to_s for %s' % self.repr())

    def getclass(self):
        raise UnsupportedOperation('no class for %s' % self.repr())

    def lookup_method(self, mid):
        w_class = promote(self.getclass())
        w_method = w_class.find_method(mid)
        if w_method is None:
            raise self.no_method_error(mid)
        return w_method

    def define_method(self, mid, w_method):
        raise UnsupportedOperation(
            'cannot define a method on %s' % self.repr())

    def no_method_error(self, mid):
        return UnsupportedOperation("undefined method '%s' for %s"
                                    % (symbols.name_of(mid), self.repr()))

    def repr(self):
        return '<W_Root>'
