from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_enumerator_class
from rpyyarv.objects.transparent import newint
from rpyyarv.rlib import JitDriver

TIMES = symbols.intern('times')


class W_Enumerator(W_Root):
    _immutable_fields_ = ['w_count']

    def __init__(self, w_count):
        self.w_count = w_count

    def getclass(self):
        return w_enumerator_class

    def repr(self):
        return '#<Enumerator: %s:times>' % self.w_count.repr()


class W_EnumeratorEach(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Enumerator)
        if w_block is None:
            return w_recv
        w_count = w_recv.w_count
        return interp.call_method(w_count.lookup_method(TIMES), w_count, [],
                                  w_block)


def _map_location(w_iseq):
    return 'times.map { %s }' % w_iseq.name


map_driver = JitDriver(name='times_map', greens=['w_iseq'], reds='auto',
                       get_printable_location=_map_location)


class W_EnumeratorMap(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Enumerator)
        if w_block is None:
            raise UnsupportedOperation(
                "map without a block (an Enumerator) is not supported yet")
        n = w_recv.w_count.int_w()
        w_iseq = w_block.w_iseq
        result_w = []
        i = 0
        while i < n:
            map_driver.jit_merge_point(w_iseq=w_iseq)
            result_w.append(interp.call_block(w_block, [newint(i)]))
            i += 1
        return W_Array(result_w)


class W_EnumeratorToA(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Enumerator)
        n = w_recv.w_count.int_w()
        items_w = []
        i = 0
        while i < n:
            items_w.append(newint(i))
            i += 1
        return W_Array(items_w)


def install(w_class):
    for name, cls in [('each', W_EnumeratorEach), ('map', W_EnumeratorMap),
                      ('to_a', W_EnumeratorToA)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, 0))
