from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.iseq import W_Block
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_hash_class, w_proc_class, w_symbol_class
from rpyyarv.objects.transparent import describe_conversion, w_nil


class W_Proc(W_Root):
    _immutable_fields_ = ['w_block']

    def __init__(self, w_block):
        self.w_block = w_block

    def getclass(self):
        return w_proc_class

    def repr(self):
        return '<W_Proc %s>' % self.w_block.w_iseq.name


def block_proc(w_block):
    if w_block.w_proc is None:
        w_block.w_proc = W_Proc(w_block)
    return w_block.w_proc


TO_PROC = symbols.intern('to_proc')


def block_of(w_arg):
    if w_arg is w_nil:
        return None
    if isinstance(w_arg, W_Proc):
        return w_arg.w_block
    # Symbol and Hash have a to_proc in CRuby that RPyYARV lacks
    if (w_arg.getclass() is w_symbol_class or w_arg.getclass() is w_hash_class
            or w_arg.lookup_class().find_method(TO_PROC) is not None):
        raise UnsupportedOperation('&%s through to_proc is not supported yet'
                                   % w_arg.getclass().name)
    raise UnsupportedOperation('no implicit conversion of %s into Proc'
                               % describe_conversion(w_arg))


class W_MakeProc(W_CFunc):
    _immutable_fields_ = ['is_lambda']

    def __init__(self, mid, is_lambda):
        W_CFunc.__init__(self, mid, 0, True)
        self.is_lambda = is_lambda

    def call(self, w_recv, args_w, w_block):
        if w_block is None:
            raise UnsupportedOperation(
                'tried to create Proc object without a block')
        if w_block.w_proc is not None:
            if self.is_lambda:
                raise UnsupportedOperation(
                    'the lambda method requires a literal block')
            return w_block.w_proc
        return block_proc(W_Block(w_block.w_iseq, w_block.w_self,
                                  w_block.outer, self.is_lambda))


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
