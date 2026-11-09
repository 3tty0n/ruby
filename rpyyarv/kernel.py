"""Builtin methods, installed on Object."""

import os

from rpyyarv import optable
from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.klass import BOP_EQ
from rpyyarv.objects.string import W_String
from rpyyarv.objects.instance import W_Object
from rpyyarv.objects.symbol import W_Symbol, newsymbol
from rpyyarv.objects.transparent import (W_Integer, newbool, newint, w_false,
                                         w_nil, w_true)
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
            for w_item in w_arg.items():
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


class W_CaseEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return newbool(equal(w_recv, args_w[0]))


class W_CaseEqualNotYet(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        raise UnsupportedOperation('%s#=== is not supported yet'
                                   % w_recv.getclass().name)


class W_Not(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return newbool(not w_recv.is_true())


EQ = symbols.intern('==')
EQQ = symbols.intern('===')
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
            w_copy = W_Array(w_recv.items()[:])
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


def install_case_equal(w_class, cls=W_CaseEqual):
    w_class.add_method(EQQ, cls(EQQ, 1))


METHOD_MISSING = symbols.intern('method_missing')


class W_MethodMissing(W_CFunc):
    _immutable_fields_ = ['w_target']

    def __init__(self, mid, w_target):
        W_CFunc.__init__(self, mid, -1)
        self.w_target = w_target

    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        return interp.call_method(self.w_target, w_recv,
                                  [newsymbol(self.mid)] + args_w, w_block)


def method_missing(w_recv, w_class, mid):
    w_target = w_class.find_method(METHOD_MISSING)
    if w_target is None:
        raise w_recv.no_method_error(mid)
    if not isinstance(w_recv, W_Object):
        raise UnsupportedOperation('method_missing on %s is not supported yet'
                                   % w_recv.repr())
    # Lacking a method CRuby's Object has is RPyYARV's gap, not a miss
    name = symbols.name_of(mid)
    if name in optable.CRUBY_OBJECT_METHODS:
        raise UnsupportedOperation('Object#%s is not supported yet' % name)
    return W_MethodMissing(mid, w_target)


class W_Send(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        if len(args_w) == 0:
            raise UnsupportedOperation('no method name given')
        w_name = args_w[0]
        if isinstance(w_name, W_Symbol):
            mid = w_name.mid
        elif isinstance(w_name, W_String):
            mid = symbols.intern(w_name.strval)
        else:
            raise UnsupportedOperation('%s is not a symbol nor a string'
                                       % w_name.repr())
        return interp.call_method(w_recv.lookup_method(mid), w_recv,
                                  args_w[1:], w_block)


class W_KernelInteger(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        if len(args_w) != 1:
            raise UnsupportedOperation(
                'Integer() with a base or options is not supported yet')
        w_arg = args_w[0]
        if not isinstance(w_arg, W_Integer):
            raise UnsupportedOperation('Integer() of %s is not supported yet'
                                       % w_arg.getclass().name)
        return w_arg


def install(w_class):
    puts_id = symbols.intern('puts')
    w_class.add_method(puts_id, W_Puts(puts_id, -1, True))  # Kernel#puts is private
    to_s_id = symbols.intern('to_s')
    w_class.add_method(to_s_id, W_ToS(to_s_id, 0))
    integer_id = symbols.intern('Integer')
    w_class.add_method(integer_id, W_KernelInteger(integer_id, -1, True))
    now_id = symbols.intern('bench_now_ns')
    w_class.add_method(now_id, W_BenchNowNs(now_id, 0))
    for name, cls, arity in [('==', W_Equal, 1), ('!=', W_NotEqual, 1),
                             ('!', W_Not, 0), ('dup', W_Dup, 0),
                             ('clone', W_Dup, 0), ('send', W_Send, -1),
                             ('__send__', W_Send, -1)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
