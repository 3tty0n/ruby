"""proc.c + vm_method.c: Proc, blocks, and the C trampoline."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv import symbols
from rpyyarv.boot._core import (_ext, _v, VALUE, VALUEP, INTP, MAX_ARGC,
                                BLOCK_HOOK, TRAMP_HOOK, _enter_status,
                                _leave_status, _enter_argv, _leave_argv,
                                _failed, _failed_mid, RubyError)


rb_call0 = _ext('rpyyarv_call0', [VALUE, rffi.CCHARP, INTP], VALUE, reenters=True)


rb_funcallv_id = _ext('rpyyarv_funcallv_id',
                      [VALUE, VALUE, rffi.INT, VALUEP, INTP], VALUE, reenters=True)


rb_funcallv_public_id = _ext('rpyyarv_funcallv_public_id',
                             [VALUE, VALUE, rffi.INT, VALUEP, INTP], VALUE,
                             reenters=True)


rb_funcallv_kw_id = _ext('rpyyarv_funcallv_kw_id',
                         [VALUE, VALUE, rffi.INT, VALUEP, rffi.INT, INTP],
                         VALUE, reenters=True)


rb_set_block_callback = _ext('rpyyarv_set_block_callback', [BLOCK_HOOK],
                             lltype.Void)


rb_call_with_block = _ext('rpyyarv_call_with_block',
                          [VALUE, VALUE, rffi.INT, VALUEP, rffi.LONG,
                           rffi.INT, INTP], VALUE, reenters=True)


rb_call_with_proc = _ext('rpyyarv_call_with_proc',
                         [VALUE, VALUE, rffi.INT, VALUEP, VALUE,
                          rffi.INT, INTP], VALUE, reenters=True)


rb_set_trampoline_callback = _ext('rpyyarv_set_trampoline_callback',
                                  [TRAMP_HOOK], lltype.Void)


rb_define_method_id = _ext('rpyyarv_define_method',
                           [VALUE, VALUE, rffi.INT, INTP], VALUE,
                           reenters=True)


rb_proc_new = _ext('rpyyarv_proc_new', [rffi.LONG, INTP], VALUE, reenters=True)


rb_pop_dead_handle = _ext('rpyyarv_pop_dead_handle', [], rffi.LONG)


rb_is_proc = _ext('rpyyarv_is_proc', [VALUE], rffi.INT)


rb_block_sentinel = _ext('rpyyarv_block_sentinel', [], VALUE, reenters=True)


rb_proc_handle = _ext('rpyyarv_proc_handle', [VALUE], rffi.LONG)


rb_yield_values = _ext('rpyyarv_yield_values',
                       [rffi.INT, VALUEP, rffi.INT, INTP], VALUE,
                       reenters=True)


YIELD_OK = 0
YIELD_BREAK = 1
YIELD_RAISE = 2
YIELD_TAG = 3


def yield_values(args, kw):
    """Yield to the block of the trampoline frame; (value, state)."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError('yield')
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    with lltype.scoped_alloc(INTP.TO, 1) as st:
        st[0] = rffi.cast(rffi.INT, 0)
        v = rb_yield_values(rffi.cast(rffi.INT, argc), argv,
                            rffi.cast(rffi.INT, 1 if kw else 0), st)
        state = rffi.cast(lltype.Signed, st[0])
    _leave_argv(argv)
    if state == YIELD_RAISE:
        _failed('yield')
    return rffi.cast(lltype.Signed, v), state


rb_kw_hash_p = _ext('rpyyarv_kw_hash_p', [VALUE], rffi.INT)


rb_kw_hash_dup = _ext('rpyyarv_kw_hash_dup', [VALUE, INTP], VALUE,
                      reenters=True)


rb_call_super = _ext('rpyyarv_call_super',
                     [VALUE, VALUE, VALUE, VALUE, rffi.INT, VALUEP,
                      rffi.INT, VALUE, INTP],
                     VALUE, reenters=True)


def call0(recv, mid):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        with rffi.scoped_str2charp(mid) as c_mid:
            v = rb_call0(_v(recv), c_mid, state)
        if rffi.cast(lltype.Signed, state[0]) != 0:
            raise RubyError(mid)
        return rffi.cast(lltype.Signed, v)


def funcallv(recv, rid, args, mid, public_only=False):
    """public_only picks rb_funcallv_public, which honours visibility."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    if public_only:
        v = rb_funcallv_public_id(
            rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
            rffi.cast(rffi.INT, argc), argv, state)
    else:
        v = rb_funcallv_id(
            rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
            rffi.cast(rffi.INT, argc), argv, state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def funcallv_kw(recv, rid, args, mid, public_only=False):
    """args[-1] must be a Hash; it reaches the callee as keywords."""
    argc = len(args)
    if argc > MAX_ARGC or argc < 1:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_funcallv_kw_id(
        rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
        rffi.cast(rffi.INT, argc), argv,
        rffi.cast(rffi.INT, 1 if public_only else 0), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def call_with_proc(recv, rid, args, proc, mid, kw=False):
    """CRuby runs the Proc itself, so its cref and break/return stay CRuby's."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_call_with_proc(_v(recv), _v(rid),
                          rffi.cast(rffi.INT, argc), argv, _v(proc),
                          rffi.cast(rffi.INT, 1 if kw else 0), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def call_with_block(recv, rid, args, handle, mid, kw=False):
    """kw: args[-1] is a Hash the callee should see as keywords."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_call_with_block(_v(recv), _v(rid),
                           rffi.cast(rffi.INT, argc), argv,
                           rffi.cast(rffi.LONG, handle),
                           rffi.cast(rffi.INT, 1 if kw else 0), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def install_block_callback(fn):
    """Plain function, not an llhelper: rffi builds the enter-from-C wrapper."""
    rb_set_block_callback(fn)


def install_trampoline_callback(fn):
    rb_set_trampoline_callback(fn)


def define_method_entry(klass, rid, visibility):
    """A CRuby method entry over the generic trampoline; returns its def key.
    visibility is 0 public, 1 private, 2 protected, as the shim spells it."""
    state = _enter_status()
    key = rb_define_method_id(_v(klass), _v(rid),
                              rffi.cast(rffi.INT, visibility), state)
    failed = _leave_status(state)
    if failed:
        _failed('define_method')
    return rffi.cast(lltype.Signed, key)


def as_signed(v):
    return rffi.cast(lltype.Signed, v)


def as_int(v):
    """An rffi.INT from the shim, widened for RPython arithmetic."""
    return rffi.cast(lltype.Signed, v)


def store_int(p, n):
    p[0] = rffi.cast(rffi.INT, n)


def store_value(p, v):
    p[0] = rffi.cast(VALUE, v)


def read_values(argv, argc):
    """The yielded values out of the shim's machine-stack buffer."""
    n = rffi.cast(lltype.Signed, argc)
    out = [0] * n
    i = 0
    while i < n:
        out[i] = rffi.cast(lltype.Signed, argv[i])
        i += 1
    return out


def read_value_at(argv, i):
    """One argv slot, for a caller that writes straight into Frame locals."""
    return rffi.cast(lltype.Signed, argv[i])


def as_value(n):
    return rffi.cast(VALUE, n)


def call_super(klass, owner, recv, rid, args, mid, kw=False, proc=0):
    """The method after owner's along klass's chain: where `super` lands."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_call_super(rffi.cast(VALUE, klass), rffi.cast(VALUE, owner),
                      rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
                      rffi.cast(rffi.INT, argc), argv,
                      rffi.cast(rffi.INT, 1 if kw else 0),
                      rffi.cast(VALUE, proc), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def block_sentinel():
    """The self handle procs capture; equality means CRuby did not rebind."""
    return rffi.cast(lltype.Signed, rb_block_sentinel())


def proc_handle(v):
    """The handle a live handle-proc stands for, from the proc itself."""
    return rffi.cast(lltype.Signed, rb_proc_handle(_v(v)))


def kw_hash_p(v):
    """RHASH_PASS_AS_KEYWORDS: a ruby2_keywords-forwarded Hash."""
    return rffi.cast(lltype.Signed, rb_kw_hash_p(_v(v))) != 0


def kw_hash_dup(v):
    """A flagged copy, as Hash.ruby2_keywords_hash makes."""
    state = _enter_status()
    r = rb_kw_hash_dup(_v(v), state)
    failed = _leave_status(state)
    if failed:
        _failed('kw_hash_dup')
    return rffi.cast(lltype.Signed, r)


def proc_new(handle):
    """A Proc whose call re-enters RPyYARV through the block callback."""
    state = _enter_status()
    v = rb_proc_new(rffi.cast(rffi.LONG, handle), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Proc.new')
    return ret


def pop_dead_handle():
    return rffi.cast(lltype.Signed, rb_pop_dead_handle())


def is_proc(v):
    return rffi.cast(lltype.Signed, rb_is_proc(_v(v))) != 0
