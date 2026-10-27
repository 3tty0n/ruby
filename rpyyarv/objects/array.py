from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation 
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_array_class
from rpyyarv.objects.transparent import newint, w_false, w_nil, w_true
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
    while len(items_w) <= index:
        items_w.append(w_nil)
    items_w[index] = w_value
    return w_value


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


def _join(w_ary, sep, parts):
    from rpyyarv import interp
    for w_item in w_ary.items_w:
        if isinstance(w_item, W_Array):
            _join(w_item, sep, parts)
        else:
            parts.append(interp.to_s_string(w_item).str_w())


class W_Join(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv.objects.string import W_String
        assert isinstance(w_recv, W_Array)
        if len(args_w) > 1:
            raise UnsupportedOperation(
                "wrong number of arguments to 'join' (given %d, expected 0..1)"
                % len(args_w))
        sep = ''
        if len(args_w) == 1:
            sep = args_w[0].str_w()
        parts = []
        _join(w_recv, sep, parts)
        return W_String(sep.join(parts))


class W_AryEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Array)
        w_other = args_w[0]
        if not isinstance(w_other, W_Array):
            return w_false
        if len(w_other.items_w) != len(w_recv.items_w):
            return w_false
        i = 0
        while i < len(w_recv.items_w):
            if not interp.equal(w_recv.items_w[i], w_other.items_w[i]):
                return w_false
            i += 1
        return w_true


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
