from rpyyarv.objects.base import W_Root
from rpyyarv.objects.transparent import w_nil


class W_Object(W_Root):
    def __init__(self, w_class):
        self.w_class = w_class
        self.ivars_w = {}

    def get_ivar(self, mid):
        return self.ivars_w.get(mid, w_nil)

    def set_ivar(self, mid, w_value):
        self.ivars_w[mid] = w_value

    def getclass(self):
        return self.w_class

    def to_s_str(self):
        return self.repr()

    def repr(self):
        return '#<%s>' % self.w_class.name
