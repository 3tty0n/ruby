from rpyyarv import helpers
from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_range_class
from rpyyarv.objects.string import W_String
from rpyyarv.objects.transparent import (W_Integer, newbool, newint, w_false,
                                         w_nil, w_true)
from rpyyarv.rlib import JitDriver, ovfcheck


class W_Range(W_Root):
    _immutable_fields_ = ['w_begin', 'w_end', 'exclusive']

    def __init__(self, w_begin, w_end, exclusive):
        self.w_begin = w_begin
        self.w_end = w_end
        self.exclusive = exclusive

    def getclass(self):
        return w_range_class

    def repr(self):
        dots = '...' if self.exclusive else '..'
        return '<W_Range %s%s%s>' % (self.w_begin.repr(), dots,
                                     self.w_end.repr())


def _check_end(w_x):
    if not (w_x is w_nil or helpers.is_number(w_x)
            or isinstance(w_x, W_String)):
        raise UnsupportedOperation('a Range of %s is not supported yet'
                                   % w_x.getclass().name)


def newrange(w_begin, w_end, exclusive):
    _check_end(w_begin)
    _check_end(w_end)
    if (w_begin is not w_nil and w_end is not w_nil
            and helpers.is_number(w_begin) != helpers.is_number(w_end)):
        raise UnsupportedOperation('bad value for range')
    return W_Range(w_begin, w_end, exclusive)


def _bounds(w_range, name):
    w_begin = w_range.w_begin
    w_end = w_range.w_end
    if not (isinstance(w_begin, W_Integer) and isinstance(w_end, W_Integer)):
        raise UnsupportedOperation('%s over %s..%s is not supported yet'
                                   % (name, w_begin.getclass().name,
                                      w_end.getclass().name))
    return w_begin.int_w(), w_end.int_w()


def _within(i, last, exclusive, step):
    if i == last:
        return not exclusive
    if step > 0:
        return i < last
    return i > last


def _loop_location(w_iseq):
    return 'Range loop { %s }' % w_iseq.name


loop_driver = JitDriver(name='range_loop', greens=['w_iseq'], reds='auto',
                        get_printable_location=_loop_location)


def _each(w_range, step, w_block, name):
    from rpyyarv import interp
    i, last = _bounds(w_range, name)
    w_iseq = w_block.w_iseq
    while _within(i, last, w_range.exclusive, step):
        loop_driver.jit_merge_point(w_iseq=w_iseq)
        interp.call_block(w_block, [newint(i)])
        try:
            i = ovfcheck(i + step)
        except OverflowError:
            break


class W_RangeEach(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Range)
        if w_block is None:
            raise UnsupportedOperation(
                "each without a block (an Enumerator) is not supported yet")
        _each(w_recv, 1, w_block, 'each')
        return w_recv


class W_RangeStep(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Range)
        if w_block is None:
            raise UnsupportedOperation(
                "step without a block (an ArithmeticSequence) is not "
                "supported yet")
        w_step = args_w[0]
        if not isinstance(w_step, W_Integer):
            raise UnsupportedOperation('step by %s is not supported yet'
                                       % w_step.getclass().name)
        step = w_step.int_w()
        if step == 0:
            raise UnsupportedOperation("step can't be 0")
        _each(w_recv, step, w_block, 'step')
        return w_recv


class W_RangeToA(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Range)
        i, last = _bounds(w_recv, 'to_a')
        items_w = []
        while _within(i, last, w_recv.exclusive, 1):
            items_w.append(newint(i))
            try:
                i = ovfcheck(i + 1)
            except OverflowError:
                break
        return W_Array(items_w)


class W_RangeEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import kernel
        assert isinstance(w_recv, W_Range)
        w_other = args_w[0]
        if w_recv is w_other:
            return w_true
        if (not isinstance(w_other, W_Range)
                or w_other.exclusive != w_recv.exclusive):
            return w_false
        return newbool(kernel.equal(w_recv.w_begin, w_other.w_begin)
                       and kernel.equal(w_recv.w_end, w_other.w_end))


def install(w_class):
    for name, cls, arity in [('each', W_RangeEach, 0),
                             ('step', W_RangeStep, 1),
                             ('to_a', W_RangeToA, 0),
                             ('==', W_RangeEqual, 1)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
