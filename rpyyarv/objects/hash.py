from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.klass import w_hash_class
from rpyyarv.objects.string import W_String
from rpyyarv.objects.symbol import W_Symbol
from rpyyarv.objects.transparent import (W_Integer, newbool, newint, w_false,
                                         w_nil, w_true)
from rpyyarv.rlib import (JitDriver, compute_hash, compute_identity_hash,
                          r_dict)


def _key_eq(w_a, w_b):
    if isinstance(w_a, W_Integer) and isinstance(w_b, W_Integer):
        return w_a.int_w() == w_b.int_w()
    if isinstance(w_a, W_String) and isinstance(w_b, W_String):
        return w_a.strval == w_b.strval
    return w_a is w_b


def _key_hash(w_key):
    if isinstance(w_key, W_Integer):
        return w_key.int_w()
    if isinstance(w_key, W_String):
        return compute_hash(w_key.strval)
    return compute_identity_hash(w_key)


class W_Hash(W_Root):
    def __init__(self):
        self.positions = r_dict(_key_eq, _key_hash)
        self.keys_w = []
        self.values_w = []
        self.iterating = 0

    def getclass(self):
        return w_hash_class

    def repr(self):
        return '<W_Hash %d>' % len(self.keys_w)


def lookup(w_hash, w_key):
    if not (isinstance(w_key, W_Integer) or isinstance(w_key, W_String)
            or isinstance(w_key, W_Symbol) or w_key is w_nil
            or w_key is w_true or w_key is w_false):
        raise UnsupportedOperation('a Hash key of class %s is not supported '
                                   'yet' % w_key.getclass().name)
    return w_hash.positions.get(w_key, -1)


def aset(w_hash, w_key, w_value):
    i = lookup(w_hash, w_key)
    if i >= 0:
        w_hash.values_w[i] = w_value
        return
    if w_hash.iterating > 0:
        raise UnsupportedOperation(
            "can't add a new key into hash during iteration")
    w_hash.positions[w_key] = len(w_hash.keys_w)
    w_hash.keys_w.append(w_key)
    w_hash.values_w.append(w_value)


def copy(w_hash):
    w_copy = W_Hash()
    i = 0
    while i < len(w_hash.keys_w):
        aset(w_copy, w_hash.keys_w[i], w_hash.values_w[i])
        i += 1
    return w_copy


class W_HashAref(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Hash)
        i = lookup(w_recv, args_w[0])
        if i < 0:
            return w_nil
        return w_recv.values_w[i]


class W_HashAset(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Hash)
        aset(w_recv, args_w[0], args_w[1])
        return args_w[1]


class W_HashSize(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Hash)
        return newint(len(w_recv.keys_w))


class W_HashKeys(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Hash)
        return W_Array(w_recv.keys_w[:])


class W_HashValues(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Hash)
        return W_Array(w_recv.values_w[:])


class W_HashToA(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Hash)
        pairs_w = []
        i = 0
        while i < len(w_recv.keys_w):
            pairs_w.append(W_Array([w_recv.keys_w[i], w_recv.values_w[i]]))
            i += 1
        return W_Array(pairs_w)


class W_HashHasKey(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_Hash)
        return newbool(lookup(w_recv, args_w[0]) >= 0)


def _each_location(w_iseq):
    return 'Hash#each { %s }' % w_iseq.name


each_driver = JitDriver(name='hash_each', greens=['w_iseq'], reds='auto',
                        get_printable_location=_each_location)


class W_HashEach(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import interp
        assert isinstance(w_recv, W_Hash)
        if w_block is None:
            raise UnsupportedOperation(
                "each without a block (an Enumerator) is not supported yet")
        w_iseq = w_block.w_iseq
        pairwise = w_iseq.nparams > 1
        w_recv.iterating += 1
        i = 0
        while i < len(w_recv.keys_w):
            each_driver.jit_merge_point(w_iseq=w_iseq)
            w_key = w_recv.keys_w[i]
            w_value = w_recv.values_w[i]
            if pairwise:
                interp.call_block(w_block, [w_key, w_value])
            else:
                interp.call_block(w_block, [W_Array([w_key, w_value])])
            i += 1
        w_recv.iterating -= 1
        return w_recv


_comparing_w = []


class W_HashEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        from rpyyarv import kernel
        assert isinstance(w_recv, W_Hash)
        w_other = args_w[0]
        if w_recv is w_other:
            return w_true
        if not isinstance(w_other, W_Hash):
            return w_false
        if len(w_other.keys_w) != len(w_recv.keys_w):
            return w_false
        i = 0
        while i < len(_comparing_w):
            if _comparing_w[i] is w_recv and _comparing_w[i + 1] is w_other:
                return w_true
            i += 2
        _comparing_w.append(w_recv)
        _comparing_w.append(w_other)
        w_recv.iterating += 1
        try:
            i = 0
            while i < len(w_recv.keys_w):
                j = lookup(w_other, w_recv.keys_w[i])
                if j < 0 or not kernel.equal(w_recv.values_w[i],
                                             w_other.values_w[j]):
                    return w_false
                i += 1
            return w_true
        finally:
            w_recv.iterating -= 1
            _comparing_w.pop()
            _comparing_w.pop()


def install(w_class):
    for name, cls, arity in [('[]', W_HashAref, 1), ('[]=', W_HashAset, 2),
                             ('size', W_HashSize, 0),
                             ('length', W_HashSize, 0),
                             ('keys', W_HashKeys, 0),
                             ('values', W_HashValues, 0),
                             ('to_a', W_HashToA, 0),
                             ('key?', W_HashHasKey, 1),
                             ('each', W_HashEach, 0),
                             ('==', W_HashEqual, 1)]:
        mid = symbols.intern(name)
        w_class.add_method(mid, cls(mid, arity))
