from error import UnsupportedOperation


class W_Root(object):
    # Only nil and false are falsy in Ruby.
    def is_true(self):
        return True

    def int_w(self):
        raise UnsupportedOperation('not an integer')

    def repr(self):
        return '<W_Root>'
