"""The one door from RPython into CRuby's method dispatch."""

from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.rlib import dont_look_inside, elidable


class _State(object):
    def __init__(self):
        # A list, not a dict: symbol ids are dense, and this is read on every foreign send. 0 means not resolved yet; no CRuby ID is 0.
        self.rids = []      # rpyyarv symbol id -> CRuby ID
        self.mids = {}      # CRuby ID -> rpyyarv symbol id
        # Same shape, for the Symbol object a keyword name becomes.
        self.syms = []      # rpyyarv symbol id -> Symbol VALUE


state = _State()


class _Stress(object):
    # Quasi-immutable, so the check folds away but entry_point's write to a prebuilt instance still invalidates it. See value._Classes.
    _immutable_fields_ = ['flag?']

    def __init__(self):
        self.flag = False


stress = _Stress()

REQUIRE = symbols.intern('require')
REQUIRE_RELATIVE = symbols.intern('require_relative')

# No VALUE is negative, so this cannot collide with a Ruby answer.
NOT_HANDLED = -1


class RequireHook(object):
    """Replaced by requires.install(); the base one hands every require back to CRuby, which is what happens when interception is off."""
    def handle(self, mid, arg):
        return NOT_HANDLED

    def from_cruby(self, arg):
        """The Kernel#require override's body; nothing defines that method until requires.install() does."""
        return value.Q_NIL


class _Relative(object):
    """The file a require_relative resolves against, stamped by the send; load.c reads a CRuby frame for this and RPyYARV pushes none."""
    def __init__(self):
        self.path = ''


relative = _Relative()


class _Hooks(object):
    # A field, not a module global: RPython freezes module globals.
    def __init__(self):
        self.require = RequireHook()


hooks = _Hooks()


@dont_look_inside
def rid(mid):
    if mid < len(state.rids):
        r = state.rids[mid]
        if r != 0:
            return r
    return _resolve_rid(mid)


def _resolve_rid(mid):
    r = boot.intern(symbols.name_of(mid))
    while len(state.rids) <= mid:
        state.rids.append(0)
    state.rids[mid] = r
    state.mids[r] = mid
    return r


@dont_look_inside
def sym_value(mid):
    """The static Symbol for an interned name; ID2SYM of an rb_intern, so CRuby pins it."""
    if mid < len(state.syms):
        v = state.syms[mid]
        if v != 0:
            return v
    v = boot.sym_new(symbols.name_of(mid))
    while len(state.syms) <= mid:
        state.syms.append(0)
    state.syms[mid] = v
    return v


NO_MID = -1


@dont_look_inside
def mid_of_rid(r):
    """The trampoline's rb_frame_this_func ID back to the id the registry is keyed on; every trampolined method went through rid() to get installed."""
    return state.mids.get(r, NO_MID)


@dont_look_inside
def call(recv, mid, args, public_only=False):
    if (mid == REQUIRE or mid == REQUIRE_RELATIVE) and len(args) == 1:
        v = hooks.require.handle(mid, args[0])
        if v != NOT_HANDLED:
            return v
    debug.count_foreign_site(mid, recv,
                             args[0] if len(args) == 1 else value.Q_UNDEF)
    return boot.funcallv(recv, rid(mid), args, mid, public_only)


@dont_look_inside
def call_kw(recv, mid, args, public_only=False):
    """args[-1] is the keyword Hash; CRuby unpacks it because of RB_PASS_KEYWORDS."""
    debug.count_foreign(mid)
    return boot.funcallv_kw(recv, rid(mid), args, mid, public_only)


@dont_look_inside
def call1(recv, mid, arg):
    debug.count_foreign_site(mid, recv, arg)
    return boot.funcallv(recv, rid(mid), [arg], mid)


@dont_look_inside
def call0(recv, mid):
    debug.count_foreign(mid)
    return boot.funcallv(recv, rid(mid), [], mid)


@dont_look_inside
def call2(recv, mid, a, b):
    debug.count_foreign(mid)
    return boot.funcallv(recv, rid(mid), [a, b], mid)


@dont_look_inside
def call_super(klass, owner, recv, mid, args, kw=False, proc=0):
    debug.count_foreign(mid)
    return boot.call_super(klass, owner, recv, rid(mid), args, mid, kw, proc)


@dont_look_inside
def call_with_proc(recv, mid, args, proc, kw=False):
    debug.count_foreign(mid)
    return boot.call_with_proc(recv, rid(mid), args, proc, mid, kw)


@dont_look_inside
def call_with_block(recv, mid, args, handle, kw=False):
    debug.count_foreign(mid)
    return boot.call_with_block(recv, rid(mid), args, handle, mid, kw)


@dont_look_inside
def ary_resurrect(ary):
    return boot.ary_resurrect(ary)


@dont_look_inside
def ary_store(ary, idx, val):
    # A call, not a raw store: rb_ary_store runs the write barrier.
    boot.ary_store(ary, idx, val)


@dont_look_inside
def ary_new(values):
    return boot.ary_new(values)


@dont_look_inside
def ary_store_fresh(ary, idx, val):
    # rb_ary_store still, for the write barrier; only rb_protect is dropped.
    boot.ary_store_fresh(ary, idx, val)


@dont_look_inside
def ary_new_capa(capa):
    return boot.ary_new_capa_fast(capa)


@dont_look_inside
def ary_new_filled(n, val):
    return boot.ary_new_filled_fast(n, val)


@dont_look_inside
def hash_new(capa):
    return boot.hash_new(capa)


@dont_look_inside
def hash_aset(h, key, val):
    return boot.hash_aset(h, key, val)


@dont_look_inside
def keyword_error(kind, keys):
    return boot.keyword_error(kind, keys)


@dont_look_inside
def hash_resurrect(h):
    return boot.hash_resurrect(h)


@dont_look_inside
def hash_size(h):
    return boot.hash_size(h)


@dont_look_inside
def hash_lookup(h, key):
    """Qundef when the key is absent."""
    return boot.hash_lookup(h, key)


@dont_look_inside
def hash_delete(h, key):
    boot.hash_delete(h, key)


@dont_look_inside
def hash_keys(h):
    return boot.hash_keys(h)


@dont_look_inside
def to_hash_type(v):
    return boot.to_hash_type(v)


@dont_look_inside
def splat_array(ary, flag):
    return boot.splat_array(ary, 1 if flag else 0)


@dont_look_inside
def concat_array(ary1, ary2, to):
    return boot.concat_array(ary1, ary2, to)


@dont_look_inside
def range_new(low, high, excl):
    return boot.range_new(low, high, excl)


@dont_look_inside
def gvar_get(mid):
    return boot.gvar_get(symbols.name_of(mid))


@dont_look_inside
def gvar_set(mid, v):
    boot.gvar_set(symbols.name_of(mid), v)


@dont_look_inside
def swap_errinfo(v):
    return boot.swap_errinfo(v)


@dont_look_inside
def to_bignum(n):
    return boot.int2inum(n)


@dont_look_inside
def to_heap_float(d):
    return boot.float_new(d)


@dont_look_inside
def is_string(v):
    return not value.is_immediate(v) and boot.is_string(v)


@elidable
def const_rid(mid):
    """rid for a mid the trace already knows: folds to a constant."""
    return rid(mid)


@dont_look_inside
def _gc_start():
    boot.gc_start()


def gc_stress_point():
    """RPYYARV_GC_STRESS=1: a full GC at every dispatch."""
    if stress.flag:
        _gc_start()
