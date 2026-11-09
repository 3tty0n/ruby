"""Class#new: allocate an instance, then run the class's initialize.

Also the attribute definitions a class body calls on itself, and alias and
undef, which CRuby sends to its FrozenCore object.
"""

from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc, W_Undefined
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.instance import W_Object
from rpyyarv.objects.klass import (W_Class, w_array_class,
                                   w_frozen_core_class, w_object_class)
from rpyyarv.objects.string import W_String
from rpyyarv.objects.symbol import W_Symbol, newsymbol
from rpyyarv.objects.transparent import w_false, w_nil, w_true

INITIALIZE = symbols.intern('initialize')


def allocate(w_class):
    if w_class is w_array_class:
        return W_Array([])
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
        defined_w = []
        for w_name in args_w:
            name = _attr_name(w_name)
            ivar = symbols.intern('@' + name)
            if self.reader:
                mid = symbols.intern(name)
                w_recv.add_user_method(mid, W_AttrReader(mid, ivar))
                defined_w.append(newsymbol(mid))
            if self.writer:
                mid = symbols.intern(name + '=')
                w_recv.add_user_method(mid, W_AttrWriter(mid, ivar))
                defined_w.append(newsymbol(mid))
        return W_Array(defined_w)


w_frozen_core = W_Object(w_frozen_core_class)


def _method_name_error(w_cbase, mid):
    kind = 'module' if w_cbase.is_module else 'class'
    return UnsupportedOperation("undefined method '%s' for %s '%s'"
                                % (symbols.name_of(mid), kind, w_cbase.name))


class W_SetMethodAlias(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        w_cbase, w_new, w_old = args_w[0], args_w[1], args_w[2]
        assert isinstance(w_cbase, W_Class)
        assert isinstance(w_new, W_Symbol)
        assert isinstance(w_old, W_Symbol)
        w_method = w_cbase.find_method(w_old.mid)
        if w_method is None:
            raise _method_name_error(w_cbase, w_old.mid)
        w_cbase.add_user_method(w_new.mid, w_method)
        return w_nil


class W_UndefMethod(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        w_cbase, w_name = args_w[0], args_w[1]
        assert isinstance(w_cbase, W_Class)
        assert isinstance(w_name, W_Symbol)
        if w_cbase.find_method(w_name.mid) is None:
            raise _method_name_error(w_cbase, w_name.mid)
        w_cbase.add_user_method(w_name.mid, W_Undefined(w_name.mid))
        return w_nil


def install(w_class):
    mid = symbols.intern('new')
    w_class.add_method(mid, W_New(mid, -1))
    for name, reader, writer in [('attr_reader', True, False),
                                 ('attr_writer', False, True),
                                 ('attr_accessor', True, True)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_Attr(mid, reader, writer))


class W_ModuleCaseEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        w_class = args_w[0].getclass()
        while w_class is not None:
            if w_class is w_recv:
                return w_true
            w_class = w_class.w_superclass
        return w_false


def install_module(w_class):
    mid = symbols.intern('===')
    w_class.add_method(mid, W_ModuleCaseEqual(mid, 1))


def install_object(w_class):
    w_class.add_method(INITIALIZE, W_Initialize(INITIALIZE, 0, True))


def install_frozen_core(w_class):
    for name, cls, arity in [('core#set_method_alias', W_SetMethodAlias, 3),
                             ('core#undef_method', W_UndefMethod, 2)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
