from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation 
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_array_class, w_range_class
from rpyyarv.objects.transparent import (W_Integer, describe_conversion,
                                         newbool, newint, w_false, w_nil,
                                         w_true)
from rpyyarv.rlib import JitDriver


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
    if index >= len(items_w):
        _grow(items_w, index)
    items_w[index] = w_value
    return w_value


def _grow(items_w, index):
    while len(items_w) <= index:
        items_w.append(w_nil)


class W_Aref(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        return aref(w_recv, args_w[0].int_w())


class W_Aset(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        return aset(w_recv, args_w[0].int_w(), args_w[1])


class W_Length(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        return newint(len(w_recv.items_w))


def _each_location(w_iseq):
    return 'each { %s }' % w_iseq.name


def _map_location(w_iseq):
    return 'map { %s }' % w_iseq.name


each_driver = JitDriver(name='each', greens=['w_iseq'], reds='auto',
                        get_printable_location=_each_location)
map_driver = JitDriver(name='map', greens=['w_iseq'], reds='auto',
                       get_printable_location=_map_location)


class W_Each(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Array)
        if w_block is None:
            raise UnsupportedOperation(
                "each without a block (an Enumerator) is not supported yet")
        w_iseq = w_block.w_iseq
        i = 0
        while i < len(w_recv.items_w):
            each_driver.jit_merge_point(w_iseq=w_iseq)
            interp.call_block(w_block, [w_recv.items_w[i]])
            i += 1
        return w_recv


class W_Map(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Array)
        if w_block is None:
            raise UnsupportedOperation(
                "map without a block (an Enumerator) is not supported yet")
        w_iseq = w_block.w_iseq
        result_w = []
        i = 0
        while i < len(w_recv.items_w):
            map_driver.jit_merge_point(w_iseq=w_iseq)
            result_w.append(interp.call_block(w_block, [w_recv.items_w[i]]))
            i += 1
        return W_Array(result_w)


# Nested Arrays join is inside, as rb_exec_recursive tracks them
_joining_w = []


def _join(w_ary, sep):
    from rpyyarv import interp
    parts = []
    for w_item in w_ary.items_w:
        if isinstance(w_item, W_Array):
            if w_item is w_ary or w_item in _joining_w:
                raise UnsupportedOperation(
                    'recursive array join (ArgumentError)')
            _joining_w.append(w_item)
            try:
                parts.append(_join(w_item, sep))
            finally:
                _joining_w.pop()
        else:
            parts.append(interp.to_s_string(w_item).str_w())
    return sep.join(parts)


class W_Join(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv.objects.string import W_String
        assert isinstance(w_recv, W_Array)
        if len(args_w) > 1:
            raise UnsupportedOperation(
                "wrong number of arguments to 'join' (given %d, expected 0..1)"
                % len(args_w))
        sep = ''
        if len(args_w) == 1 and args_w[0] is not w_nil:
            sep = args_w[0].str_w()
        return W_String(_join(w_recv, sep))


# Pairs Array#== is comparing, as rb_exec_recursive_paired tracks them
_comparing_w = []


class W_AryEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import kernel
        assert isinstance(w_recv, W_Array)
        w_other = args_w[0]
        if w_recv is w_other:
            return w_true
        if not isinstance(w_other, W_Array):
            return w_false
        if len(w_other.items_w) != len(w_recv.items_w):
            return w_false
        i = 0
        while i < len(_comparing_w):
            if _comparing_w[i] is w_recv and _comparing_w[i + 1] is w_other:
                return w_true
            i += 2
        _comparing_w.append(w_recv)
        _comparing_w.append(w_other)
        try:
            i = 0
            while i < len(w_recv.items_w):
                if not kernel.equal(w_recv.items_w[i], w_other.items_w[i]):
                    return w_false
                if len(w_recv.items_w) != len(w_other.items_w):
                    return w_false
                i += 1
            return w_true
        finally:
            _comparing_w.pop()
            _comparing_w.pop()


# ARY_MAX_SIZE on a 64-bit CRuby
MAX_SIZE = 1 << 60


def _to_int(w_x):
    from rpyyarv.objects.float import W_Float
    if isinstance(w_x, W_Integer):
        return w_x.int_w()
    if isinstance(w_x, W_Float):
        f = w_x.floatval
        if not -MAX_SIZE < f < MAX_SIZE:
            raise UnsupportedOperation('%s as a size or an index is not '
                                       'supported' % w_x.repr())
        return int(f)
    if w_x is w_nil:
        raise UnsupportedOperation(
            'no implicit conversion from nil to integer')
    raise UnsupportedOperation('no implicit conversion of %s into Integer'
                               % describe_conversion(w_x))


def _size_of(w_size):
    n = _to_int(w_size)
    if n < 0:
        raise UnsupportedOperation('negative array size')
    if n > MAX_SIZE:
        raise UnsupportedOperation('array size too big')
    return n


def _new_location(w_iseq):
    return 'Array.new { %s }' % w_iseq.name


new_driver = JitDriver(name='array_new', greens=['w_iseq'], reds='auto',
                       get_printable_location=_new_location)


class W_ArrayInitialize(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Array)
        if len(args_w) > 2:
            raise UnsupportedOperation(
                "wrong number of arguments to 'initialize' (given %d, "
                "expected 0..2)" % len(args_w))
        if len(args_w) == 0:
            w_recv.items_w = []
            return w_recv
        w_size = args_w[0]
        if len(args_w) == 1 and isinstance(w_size, W_Array):
            w_recv.items_w = w_size.items_w[:]
            return w_recv
        n = _size_of(w_size)
        if w_block is None:
            w_fill = w_nil
            if len(args_w) == 2:
                w_fill = args_w[1]
            w_recv.items_w = [w_fill] * n
            return w_recv
        w_iseq = w_block.w_iseq
        items_w = []
        i = 0
        while i < n:
            new_driver.jit_merge_point(w_iseq=w_iseq)
            items_w.append(interp.call_block(w_block, [newint(i)]))
            i += 1
        w_recv.items_w = items_w
        return w_recv


def _arity_error(name, given, expected):
    return UnsupportedOperation(
        "wrong number of arguments to '%s' (given %d, expected %s)"
        % (name, given, expected))


class W_At(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        return aref(w_recv, _to_int(args_w[0]))


class W_First(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        if len(args_w) > 1:
            raise _arity_error('first', len(args_w), '0..1')
        if len(args_w) == 0:
            return aref(w_recv, 0)
        return W_Array(w_recv.items_w[:_size_of(args_w[0])])


class W_Push(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        w_recv.items_w.extend(args_w)
        return w_recv


class W_Pop(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        items_w = w_recv.items_w
        if len(args_w) > 1:
            raise _arity_error('pop', len(args_w), '0..1')
        if len(args_w) == 0:
            if len(items_w) == 0:
                return w_nil
            return items_w.pop()
        start = len(items_w) - _size_of(args_w[0])
        if start < 0:
            start = 0
        w_popped = W_Array(items_w[start:])
        del items_w[start:]
        return w_popped


class W_Shift(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        items_w = w_recv.items_w
        if len(args_w) > 1:
            raise _arity_error('shift', len(args_w), '0..1')
        if len(args_w) == 0:
            if len(items_w) == 0:
                return w_nil
            return items_w.pop(0)
        stop = _size_of(args_w[0])
        if stop > len(items_w):
            stop = len(items_w)
        w_shifted = W_Array(items_w[:stop])
        del items_w[:stop]
        return w_shifted


class W_Insert(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        if len(args_w) == 0:
            raise _arity_error('insert', 0, '1+')
        if len(args_w) == 1:
            return w_recv
        items_w = w_recv.items_w
        index = _to_int(args_w[0])
        at = index
        if index < 0:
            at = index + len(items_w) + 1
            if at < 0:
                raise UnsupportedOperation(
                    'index %d too small for array; minimum: -%d'
                    % (index, len(items_w) + 1))
        if at > len(items_w):
            _grow(items_w, at - 1)
        w_recv.items_w = items_w[:at] + args_w[1:] + items_w[at:]
        return w_recv


class W_EmptyP(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        return newbool(len(w_recv.items_w) == 0)


class W_Reverse(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        items_w = w_recv.items_w[:]
        items_w.reverse()
        return W_Array(items_w)


class W_ReverseBang(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        w_recv.items_w.reverse()
        return w_recv


class W_SliceBang(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        items_w = w_recv.items_w
        if len(args_w) == 0 or len(args_w) > 2:
            raise _arity_error('slice!', len(args_w), '1..2')
        if args_w[0].getclass() is w_range_class:
            raise UnsupportedOperation(
                'slice! with a Range is not supported yet')
        start = _to_int(args_w[0])
        if start < 0:
            start += len(items_w)
        if len(args_w) == 1:
            if start < 0 or start >= len(items_w):
                return w_nil
            return items_w.pop(start)
        length = _to_int(args_w[1])
        if length < 0 or start < 0 or start > len(items_w):
            return w_nil
        stop = len(items_w)
        if length < stop - start:
            stop = start + length
        w_sliced = W_Array(items_w[start:stop])
        del items_w[start:stop]
        return w_sliced


class W_AryPlus(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Array)
        w_other = args_w[0]
        if not isinstance(w_other, W_Array):
            raise UnsupportedOperation(
                'no implicit conversion of %s into Array'
                % describe_conversion(w_other))
        return W_Array(w_recv.items_w + w_other.items_w)


class W_AryTimes(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv.objects.string import W_String
        assert isinstance(w_recv, W_Array)
        w_other = args_w[0]
        if isinstance(w_other, W_String):
            return W_String(_join(w_recv, w_other.strval))
        n = _to_int(w_other)
        if n < 0:
            raise UnsupportedOperation('negative argument')
        if n > 0 and len(w_recv.items_w) > MAX_SIZE // n:
            raise UnsupportedOperation('argument too big')
        return W_Array(w_recv.items_w * n)


_inspecting_w = []
INSPECT = symbols.intern('inspect')


class W_AryInspect(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        from rpyyarv.objects.string import W_String
        assert isinstance(w_recv, W_Array)
        if w_recv in _inspecting_w:
            return W_String('[...]')
        _inspecting_w.append(w_recv)
        try:
            parts = []
            for w_item in w_recv.items_w:
                w_str = interp.send(w_item, INSPECT, [])
                if not isinstance(w_str, W_String):
                    raise UnsupportedOperation(
                        'inspect on %s did not return a String'
                        % w_item.repr())
                parts.append(w_str.strval)
            return W_String('[' + ', '.join(parts) + ']')
        finally:
            _inspecting_w.pop()


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
    for name in ['length', 'size']:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_Length(mid, 0))
    for name, cls, arity in [('each', W_Each, 0), ('map', W_Map, 0),
                             ('join', W_Join, -1)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
    eq_id = symbols.intern('==')
    w_class.add_method(eq_id, W_AryEqual(eq_id, 1))
    init_id = symbols.intern('initialize')
    w_class.add_method(init_id, W_ArrayInitialize(init_id, -1, True))
    for name, cls, arity in [('at', W_At, 1), ('first', W_First, -1),
                             ('push', W_Push, -1), ('pop', W_Pop, -1),
                             ('shift', W_Shift, -1),
                             ('insert', W_Insert, -1),
                             ('empty?', W_EmptyP, 0),
                             ('reverse', W_Reverse, 0),
                             ('reverse!', W_ReverseBang, 0),
                             ('slice!', W_SliceBang, -1),
                             ('+', W_AryPlus, 1), ('*', W_AryTimes, 1),
                             ('inspect', W_AryInspect, 0),
                             ('to_s', W_AryInspect, 0)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
