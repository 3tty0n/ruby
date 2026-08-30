"""The one door from RPython into CRuby's method dispatch."""

from rpyyarv import boot
from rpyyarv import debug
from rpyyarv.error import errinfos
from rpyyarv import symbols
from rpyyarv import threading
from rpyyarv import value
from rpyyarv.rlib import dont_look_inside, elidable


class _State(object):
    def __init__(self):
        # A list, not a dict: ids are dense; 0 means unresolved, no ID is 0.
        self.rids = []      # rpyyarv symbol id -> CRuby ID
        self.mids = {}      # CRuby ID -> rpyyarv symbol id
        # Same shape, for the Symbol object a keyword name becomes.
        self.syms = []      # rpyyarv symbol id -> Symbol VALUE


state = _State()


class _Stress(object):
    # Quasi-immutable: the check folds away, entry_point's write kills it.
    _immutable_fields_ = ['flag?']

    def __init__(self):
        self.flag = False


stress = _Stress()

ERRINFO = symbols.intern('$!')
RAISE = symbols.intern('raise')
REQUIRE = symbols.intern('require')
REQUIRE_RELATIVE = symbols.intern('require_relative')
NEW = symbols.intern('new')
RACTOR_VALUE = symbols.intern('value')
RACTOR_TAKE = symbols.intern('take')

# No VALUE is negative, so this cannot collide with a Ruby answer.
NOT_HANDLED = -1


class RequireHook(object):
    """Replaced by requires.install(); the base hands require to CRuby."""
    def handle(self, mid, arg):
        return NOT_HANDLED

    def from_cruby(self, arg):
        """The Kernel#require override's body, defined by requires.install()."""
        return value.Q_NIL


class _Relative(object):
    """What require_relative resolves against; load.c reads a CRuby frame."""
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
    """The Symbol for an interned name; ID2SYM of rb_intern, so pinned."""
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
    """rb_frame_this_func's ID back to the id the registry is keyed on."""
    return state.mids.get(r, NO_MID)


def intern_rid(r):
    """An unseen ID interned by name, so identity checks never fly blind."""
    name = boot.id_name(r)
    if name == '':
        return NO_MID
    mid = symbols.intern(name)
    while len(state.rids) <= mid:
        state.rids.append(0)
    state.rids[mid] = r
    state.mids[r] = mid
    return mid


def _publish_errinfo_now():
    """Lend the running rescue's $! to CRuby for the length of one call."""
    stack = errinfos.stack
    if len(stack) == 0:
        return value.Q_UNDEF
    return boot.swap_errinfo(stack[len(stack) - 1])


def _publish_errinfo(mid):
    """CRuby's raise reads ec->errinfo for `cause` and for a bare re-raise."""
    if mid != RAISE:
        return value.Q_UNDEF
    return _publish_errinfo_now()


def _restore_errinfo(prev):
    if prev != value.Q_UNDEF:
        boot.swap_errinfo(prev)


@dont_look_inside
def call(recv, mid, args, public_only=False):
    if (mid == REQUIRE or mid == REQUIRE_RELATIVE) and len(args) == 1:
        v = hooks.require.handle(mid, args[0])
        if v != NOT_HANDLED:
            return v
    if debug.coverage.enabled:
        debug.count_foreign_site(mid, recv,
                                 args[0] if len(args) == 1 else value.Q_UNDEF)
    ractor_wait = ((mid == RACTOR_VALUE or mid == RACTOR_TAKE)
                   and boot.ractor_p(recv))
    native_wait = ractor_wait and boot.native_ractors_p()
    prev = _publish_errinfo(mid)
    try:
        return boot.funcallv(recv, rid(mid), args, mid, public_only,
                             ractor_wait and not native_wait)
    finally:
        _restore_errinfo(prev)
        if native_wait:
            boot.native_ractors_poll(recv)


@dont_look_inside
def calln(recv, mid, a0, a1, a2, argc, public_only=False):
    """call for argc <= 3: no args list, so a send allocates nothing."""
    if (mid == REQUIRE or mid == REQUIRE_RELATIVE) and argc == 1:
        v = hooks.require.handle(mid, a0)
        if v != NOT_HANDLED:
            return v
    if (mid == RACTOR_VALUE or mid == RACTOR_TAKE) and boot.ractor_p(recv):
        return call(recv, mid, _args_of(a0, a1, a2, argc), public_only)
    if debug.coverage.enabled:
        debug.count_foreign_site(mid, recv, a0 if argc == 1 else value.Q_UNDEF)
    prev = _publish_errinfo(mid)
    try:
        return boot.funcalln(recv, rid(mid), a0, a1, a2, argc, mid,
                             public_only)
    finally:
        _restore_errinfo(prev)


def _args_of(a0, a1, a2, argc):
    if argc == 0:
        return []
    if argc == 1:
        return [a0]
    if argc == 2:
        return [a0, a1]
    return [a0, a1, a2]


@dont_look_inside
def call_kw(recv, mid, args, public_only=False):
    """args[-1] is the keyword Hash, unpacked by RB_PASS_KEYWORDS."""
    debug.count_foreign(mid)
    prev = _publish_errinfo(mid)
    try:
        return boot.funcallv_kw(recv, rid(mid), args, mid, public_only)
    finally:
        _restore_errinfo(prev)


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
def call_with_block(recv, mid, args, handle, native, native_cref, kw=False):
    debug.count_foreign(mid)
    if mid == NEW and boot.ractor_class_p(recv):
        threading.activate()
    return boot.call_with_block(recv, rid(mid), args, handle, native,
                                native_cref, mid, kw)


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
    stack = errinfos.stack
    if len(stack) == 0:
        return boot.gvar_get(symbols.name_of(mid))
    if mid == ERRINFO:
        return stack[len(stack) - 1]
    # An alias of $! reads ec->errinfo through CRuby's own getter.
    prev = _publish_errinfo_now()
    try:
        return boot.gvar_get(symbols.name_of(mid))
    finally:
        _restore_errinfo(prev)


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
