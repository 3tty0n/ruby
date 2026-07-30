import symbols
from error import UnsupportedOperation


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

    def lookup_method(self, mid):
        raise self.no_method_error(mid)

    def define_method(self, mid, w_method):
        raise UnsupportedOperation(
            'cannot define a method on %s' % self.repr())

    def no_method_error(self, mid):
        return UnsupportedOperation("undefined method '%s' for %s"
                                    % (symbols.name_of(mid), self.repr()))

    def repr(self):
        return '<W_Root>'
