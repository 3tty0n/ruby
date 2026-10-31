from rpyyarv.objects.base import W_Root
from rpyyarv.objects.transparent import w_nil
from rpyyarv.rlib import compute_unique_id


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
        # CRuby prints the object's address, which no two runs share either
        digits = '%x' % compute_unique_id(self)
        return '#<%s:0x%s%s>' % (self.w_class.name, '0' * (16 - len(digits)),
                                 digits)

    def repr(self):
        return '#<%s>' % self.w_class.name
