from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation 
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_array_class
from rpyyarv.objects.transparent import w_nil


class W_Array(W_Root):
    def __init__(self, items_w):
        self.items_w = items_w

    def getclass(self):
        return w_array_class

    def repr(self):
        return '<W_Array %d>' % len(self.items_w)

def aref(w_ary, index):
    items_w = w_ary.items_w
    if index < 0:
        index += len(items_w)
    if 0 <= index < len(items_w):
        return items_w[index]
    return w_nil


def aset(w_ary, index, w_value):
    items_w = w_ary.items_w
    if index < 0:
        index += len(items_w)
        if index < 0:
            raise UnsupportedOperation(
                "index %d too small for array; minimum: -%d"
                % (index - len(items_w), len(items_w)))
    while len(items_w) <= index:
        items_w.append(w_nil)
    items_w[index] = w_value
    return w_value


class W_Aref(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        return aref(w_recv, args_w[0].int_w())


class W_Aset(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        return aset(w_recv, args_w[0].int_w(), args_w[1])


class W_Inject(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Array)
        if w_block is None:
            raise UnsupportedOperation(
                "inject without a block is not supported: RPyYARV has no "
                "Symbol, so inject(:+) cannot work")
        w_acc = args_w[0]
        for w_item in w_recv.items_w:
            w_acc = interp.call_block(w_block, [w_acc, w_item])
        return w_acc


def install(w_class):
    mid = symbols.intern('inject')
    w_class.add_method(mid, W_Inject(mid, 1))  # arity=1: initial value required for now
    aref_id = symbols.intern('[]')
    w_class.add_method(aref_id, W_Aref(aref_id, 1))
    aset_id = symbols.intern('[]=')
    w_class.add_method(aset_id, W_Aset(aset_id, 2))
