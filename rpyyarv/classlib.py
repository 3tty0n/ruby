"""Class#new: allocate an instance, then run the class's initialize.

Also the attribute definitions a class body calls on itself.
"""

from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.instance import W_Object
from rpyyarv.objects.klass import W_Class, w_object_class
from rpyyarv.objects.string import W_String
from rpyyarv.objects.symbol import W_Symbol, newsymbol
from rpyyarv.objects.transparent import w_nil

INITIALIZE = symbols.intern('initialize')


def allocate(w_class):
    # A built-in class other than Object needs its own kind of object
    if w_class.builtin and w_class is not w_object_class:
        raise UnsupportedOperation('%s.new is not supported yet'
                                   % w_class.name)
    return W_Object(w_class)


class W_New(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Class)       # `new` lives only on Class
        w_obj = allocate(w_recv)
        interp.call_method(w_recv.find_method(INITIALIZE), w_obj, args_w,
                           w_block)
        return w_obj


class W_Initialize(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return w_nil


class W_AttrReader(W_CFunc):
    _immutable_fields_ = ['ivar']

    def __init__(self, mid, ivar):
        W_CFunc.__init__(self, mid, 0)
        self.ivar = ivar

    def call(self, w_recv, args_w, w_block):
        return w_recv.get_ivar(self.ivar)


class W_AttrWriter(W_CFunc):
    _immutable_fields_ = ['ivar']

    def __init__(self, mid, ivar):
        W_CFunc.__init__(self, mid, 1)
        self.ivar = ivar

    def call(self, w_recv, args_w, w_block):
        w_recv.set_ivar(self.ivar, args_w[0])
        return args_w[0]


def _attr_name(w_name):
    if isinstance(w_name, W_Symbol):
        name = symbols.name_of(w_name.mid)
    elif isinstance(w_name, W_String):
        name = w_name.strval
    else:
        raise UnsupportedOperation('%s is not a symbol nor a string'
                                   % w_name.repr())
    # rb_is_local_name or rb_is_const_name, ASCII only: CRuby also takes
    # non-ASCII letters, which are refused here
    valid = len(name) > 0 and not name[0].isdigit()
    for c in name:
        if not (c.isalnum() or c == '_'):
            valid = False
    if not valid:
        raise UnsupportedOperation("invalid attribute name '%s'" % name)
    return name


class W_Attr(W_CFunc):
    _immutable_fields_ = ['reader', 'writer']

    def __init__(self, mid, reader, writer):
        W_CFunc.__init__(self, mid, -1)
        self.reader = reader
        self.writer = writer

    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Class)       # these live only on Class
        if w_recv.builtin:
            raise UnsupportedOperation(
                '%s on the built-in class %s is not supported yet'
                % (symbols.name_of(self.mid), w_recv.name))
        defined_w = []
        for w_name in args_w:
            name = _attr_name(w_name)
            ivar = symbols.intern('@' + name)
            if self.reader:
                mid = symbols.intern(name)
                w_recv.add_method(mid, W_AttrReader(mid, ivar))
                defined_w.append(newsymbol(mid))
            if self.writer:
                mid = symbols.intern(name + '=')
                w_recv.add_method(mid, W_AttrWriter(mid, ivar))
                defined_w.append(newsymbol(mid))
        return W_Array(defined_w)


def install(w_class):
    mid = symbols.intern('new')
    w_class.add_method(mid, W_New(mid, -1))
    for name, reader, writer in [('attr_reader', True, False),
                                 ('attr_writer', False, True),
                                 ('attr_accessor', True, True)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_Attr(mid, reader, writer))


def install_object(w_class):
    w_class.add_method(INITIALIZE, W_Initialize(INITIALIZE, 0, True))
