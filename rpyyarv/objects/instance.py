from objects.base import W_Root


class W_Object(W_Root):
    # No instance variables yet
    # because getinstancevariable is not implemented
    def __init__(self, w_class):
        self.w_class = w_class

    def getclass(self):
        return self.w_class

    def to_s_str(self):
        return self.repr()

    def repr(self):
        return '#<%s>' % self.w_class.name
