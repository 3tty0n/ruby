from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.iseq import W_Block
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_proc_class


class W_Proc(W_Root):
    _immutable_fields_ = ['w_block']

    def __init__(self, w_block):
        self.w_block = w_block

    def getclass(self):
        return w_proc_class

    def repr(self):
        return '<W_Proc %s>' % self.w_block.w_iseq.name


class W_MakeProc(W_CFunc):
    _immutable_fields_ = ['is_lambda']

    def __init__(self, mid, is_lambda):
        W_CFunc.__init__(self, mid, 0, True)
        self.is_lambda = is_lambda

    def call(self, w_recv, args_w, w_block):
        if w_block is None:
            raise UnsupportedOperation(
                'tried to create Proc object without a block')
        return W_Proc(W_Block(w_block.w_iseq, w_block.w_self, w_block.outer,
                              self.is_lambda))


class W_ProcCall(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Proc)
        if w_block is not None:
            raise UnsupportedOperation(
                'calling a Proc with a block is not supported yet')
        return interp.call_block(w_recv.w_block, args_w)


def install(w_class):
    for name in ['call', '[]', 'yield', '===']:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_ProcCall(mid, -1))


def install_constructors(w_class, names):
    for name in names:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_MakeProc(mid, name == 'lambda'))
