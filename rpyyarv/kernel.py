"""Builtin methods, installed on Object."""

import os

from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.klass import BOP_EQ
from rpyyarv.objects.string import W_String
from rpyyarv.objects.symbol import W_Symbol
from rpyyarv.objects.transparent import newbool, newint, w_false, w_nil, w_true
from rpyyarv.rlib import now_ns


def write(s):
    os.write(1, s)


TO_ARY = symbols.intern('to_ary')
_putting_w = []


def _puts(w_arg):
    from rpyyarv import interp
    from rpyyarv.objects.array import W_Array
    if isinstance(w_arg, W_Array):
        if w_arg in _putting_w:
            write('[...]\n')
            return
        _putting_w.append(w_arg)
        try:
            for w_item in w_arg.items_w:
                _puts(w_item)
        finally:
            _putting_w.pop()
        return
    if w_arg.lookup_class().find_method(TO_ARY) is not None:
        raise UnsupportedOperation('puts of %s, which has to_ary, is not '
                                   'supported yet' % w_arg.repr())
    s = interp.to_s_string(w_arg).str_w()
    if not s.endswith('\n'):   # CRuby adds a newline only if missing
        s += '\n'
    write(s)


class W_Puts(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        if len(args_w) == 0:
            write('\n')
        for w_arg in args_w:
            _puts(w_arg)
        return w_nil

class W_ToS(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return W_String(w_recv.to_s_str())

class W_BenchNowNs(W_CFunc):
    """Monotonic clock in integer nanoseconds, for the benchmark harness."""
    def call(self, w_recv, args_w, w_block):
        return newint(now_ns())

class W_Equal(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return newbool(w_recv is args_w[0])


class W_NotEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        return newbool(not interp.send(w_recv, EQ, args_w).is_true())


class W_Not(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return newbool(not w_recv.is_true())


EQ = symbols.intern('==')
INITIALIZE_COPY = symbols.intern('initialize_copy')


class W_Dup(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import helpers
        from rpyyarv import interp
        from rpyyarv.objects import hash as hashlib
        from rpyyarv.objects.array import W_Array
        from rpyyarv.objects.instance import W_Object
        if (helpers.is_number(w_recv) or isinstance(w_recv, W_Symbol)
                or w_recv is w_nil or w_recv is w_true or w_recv is w_false):
            return w_recv
        if isinstance(w_recv, W_Array):
            w_copy = W_Array(w_recv.items_w[:])
        elif isinstance(w_recv, hashlib.W_Hash):
            w_copy = hashlib.copy(w_recv)
        elif isinstance(w_recv, W_String):
            w_copy = W_String(w_recv.strval)
        elif isinstance(w_recv, W_Object):
            w_copy = W_Object(w_recv.w_class)
            w_copy.ivars_w = w_recv.ivars_w.copy()
        else:
            raise UnsupportedOperation('%s of %s is not supported yet'
                                       % (symbols.name_of(self.mid),
                                          w_recv.repr()))
        w_init = w_copy.getclass().find_method(INITIALIZE_COPY)
        if w_init is not None:
            interp.call_method(w_init, w_copy, [w_recv], None)
        return w_copy


def equal(w_a, w_b):
    from rpyyarv import helpers
    from rpyyarv import interp
    if w_a is w_b:
        return True
    if helpers.numeric_fast(w_a, w_b, BOP_EQ):
        return helpers.w_eq(w_a, w_b).is_true()
    return interp.send(w_a, EQ, [w_b]).is_true()


def install_to_s(w_class):
    to_s_id = symbols.intern('to_s')
    w_class.add_method(to_s_id, W_ToS(to_s_id, 0))


class W_Inspect(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return W_String(w_recv.repr())


def install_inspect(w_class):
    mid = symbols.intern('inspect')
    w_class.add_method(mid, W_Inspect(mid, 0))


def install_identity_eq(w_class):
    w_class.add_method(EQ, W_Equal(EQ, 1))

def install(w_class):
    puts_id = symbols.intern('puts')
    w_class.add_method(puts_id, W_Puts(puts_id, -1, True))  # Kernel#puts is private
    to_s_id = symbols.intern('to_s')
    w_class.add_method(to_s_id, W_ToS(to_s_id, 0))
    now_id = symbols.intern('bench_now_ns')
    w_class.add_method(now_id, W_BenchNowNs(now_id, 0))
    for name, cls, arity in [('==', W_Equal, 1), ('!=', W_NotEqual, 1),
                             ('!', W_Not, 0), ('dup', W_Dup, 0),
                             ('clone', W_Dup, 0)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
