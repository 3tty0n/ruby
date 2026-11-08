from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.array import arity_error
from rpyyarv.objects.enumerator import W_Enumerator
from rpyyarv.objects.klass import BOP_LT, w_integer_class
from rpyyarv.objects.transparent import (W_Integer, describe_operand, newbool,
                                         newint, w_false, w_nil, w_true)
from rpyyarv.rlib import JitDriver, ovfcheck


class W_Self(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return w_recv


class W_Const(W_CFunc):
    _immutable_fields_ = ['w_value']

    def __init__(self, mid, w_value):
        W_CFunc.__init__(self, mid, 0)
        self.w_value = w_value

    def call(self, w_recv, args_w, w_block):
        return self.w_value


class W_NumEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import helpers
        from rpyyarv import interp
        w_other = args_w[0]
        if helpers.is_number(w_other):
            return helpers.w_eq(w_recv, w_other)
        return newbool(interp.send(w_other, EQ, [w_recv]).is_true())


EQ = symbols.intern('==')
COERCE = symbols.intern('coerce')


class W_NumericOp(W_CFunc):
    _immutable_fields_ = ['func', 'compare']

    def __init__(self, mid, func, compare):
        W_CFunc.__init__(self, mid, 1)
        self.func = func
        self.compare = compare

    def call(self, w_recv, args_w, w_block):
        from rpyyarv import helpers
        w_other = args_w[0]
        if helpers.is_number(w_other):
            return self.func(w_recv, w_other)
        if w_other.lookup_class().find_method(COERCE) is not None:
            raise UnsupportedOperation(
                '%s with %s through coerce is not supported yet'
                % (symbols.name_of(self.mid), w_other.getclass().name))
        name = describe_operand(w_other)
        if self.compare:
            raise UnsupportedOperation('comparison of %s with %s failed'
                                       % (w_recv.getclass().name, name))
        raise UnsupportedOperation("%s can't be coerced into %s"
                                   % (name, w_recv.getclass().name))


def _times_location(w_iseq):
    return 'times { %s }' % w_iseq.name


times_driver = JitDriver(name='times', greens=['w_iseq'], reds='auto',
                         get_printable_location=_times_location)


class W_Times(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        if w_block is None:
            return W_Enumerator(w_recv)
        n = w_recv.int_w()
        w_iseq = w_block.w_iseq
        i = 0
        while i < n:
            times_driver.jit_merge_point(w_iseq=w_iseq)
            interp.call_block(w_block, [newint(i)])
            i += 1
        return w_recv


class W_Negate(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        try:
            return newint(ovfcheck(-w_recv.int_w()))
        except OverflowError:
            raise UnsupportedOperation(
                '-(%s) overflows a Fixnum: RPyYARV has no Bignum yet'
                % w_recv.repr())


class W_ToF(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv.objects.float import W_Float
        return W_Float(w_recv.float_w())


def _step_location(w_iseq):
    return 'Integer step { %s }' % w_iseq.name


step_driver = JitDriver(name='int_step', greens=['w_iseq'], reds='auto',
                        get_printable_location=_step_location)


def _step(i, last, step, w_block):
    from rpyyarv import interp
    w_iseq = w_block.w_iseq
    while (step > 0 and i <= last) or (step < 0 and i >= last):
        step_driver.jit_merge_point(w_iseq=w_iseq)
        interp.call_block(w_block, [newint(i)])
        try:
            i = ovfcheck(i + step)
        except OverflowError:
            break


class W_Upto(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        if w_block is None:
            raise UnsupportedOperation(
                "upto without a block (an Enumerator) is not supported yet")
        w_last = args_w[0]
        if not isinstance(w_last, W_Integer):
            raise UnsupportedOperation('upto to %s is not supported yet'
                                       % w_last.getclass().name)
        _step(w_recv.int_w(), w_last.int_w(), 1, w_block)
        return w_recv


class W_Step(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import kernel
        if w_block is None:
            raise UnsupportedOperation(
                "step without a block (an ArithmeticSequence) is not "
                "supported yet")
        if len(args_w) > 2:
            raise arity_error('step', len(args_w), '0..2')
        w_last = w_nil
        if len(args_w) > 0:
            w_last = args_w[0]
        w_step = newint(1)
        if len(args_w) == 2:
            w_step = args_w[1]
            if w_step is w_nil:
                raise UnsupportedOperation('step must be numeric')
            if ((isinstance(w_step, W_Integer) and w_step.int_w() == 0)
                    or kernel.equal(w_step, newint(0))):
                raise UnsupportedOperation("step can't be 0")
        if w_last is w_nil:
            raise UnsupportedOperation(
                'step without a limit (an endless loop) is not supported yet')
        if not isinstance(w_last, W_Integer):
            raise UnsupportedOperation('step to %s is not supported yet'
                                       % w_last.getclass().name)
        if not isinstance(w_step, W_Integer):
            raise UnsupportedOperation('step by %s is not supported yet'
                                       % w_step.getclass().name)
        if w_integer_class.redefined & BOP_LT:
            raise UnsupportedOperation(
                'step after redefining Integer#< is not supported yet')
        _step(w_recv.int_w(), w_last.int_w(), w_step.int_w(), w_block)
        return w_recv


def _add_self(w_class, name):
    mid = symbols.intern(name)
    w_class.add_method(mid, W_Self(mid, 0))


def _add_const(w_class, name, w_value):
    mid = symbols.intern(name)
    w_class.add_method(mid, W_Const(mid, w_value))


def install(w_class):
    _add_const(w_class, 'real?', w_true)
    _add_self(w_class, 'real')
    _add_const(w_class, 'imag', newint(0))
    _add_self(w_class, 'conj')
    _add_const(w_class, 'integer?', w_false)
    _add_const(w_class, 'finite?', w_true)
    _add_const(w_class, 'infinite?', w_nil)


def install_integer(w_class):
    from rpyyarv import helpers
    _add_const(w_class, 'integer?', w_true)
    _add_self(w_class, 'numerator')
    _add_const(w_class, 'denominator', newint(1))
    for name, cls, arity in [('times', W_Times, 0), ('to_f', W_ToF, 0),
                             ('upto', W_Upto, 1), ('step', W_Step, -1),
                             ('-@', W_Negate, 0)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
    pow_id = symbols.intern('**')
    w_class.add_method(pow_id, W_NumericOp(pow_id, helpers.w_int_pow, False))


def install_operators(w_class):
    from rpyyarv import helpers
    for name, func, compare in [('+', helpers.w_add, False),
                                ('-', helpers.w_sub, False),
                                ('*', helpers.w_mul, False),
                                ('/', helpers.w_div, False),
                                ('%', helpers.w_mod, False),
                                ('<', helpers.w_lt, True),
                                ('>', helpers.w_gt, True),
                                ('<=', helpers.w_le, True),
                                ('>=', helpers.w_ge, True)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_NumericOp(mid, func, compare))
    eq_id = symbols.intern('==')
    w_class.add_method(eq_id, W_NumEqual(eq_id, 1))
