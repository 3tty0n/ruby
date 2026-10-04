import symbols
from methods import W_CFunc
from objects.base import W_Root
from objects.klass import w_array_class


class W_Array(W_Root):
    # Only literal arrays exist so far, and nothing mutates them.
    def __init__(self, items_w):
        self.items_w = items_w

    def getclass(self):
        return w_array_class

    def repr(self):
        return '<W_Array %d>' % len(self.items_w)

class W_Inject(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        import interp
        assert isinstance(w_recv, W_Array)
        w_acc = args_w[0]
        for w_item in w_recv.items_w:
            w_acc = interp.call_block(w_block, [w_acc, w_item])
        return w_acc


def install(w_class):
    mid = symbols.intern('inject')
    w_class.add_method(mid, W_Inject(mid, 1))  # arity=1: initial value required for now