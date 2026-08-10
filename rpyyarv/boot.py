import os
import sys

from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.translator.tool.cbuild import ExternalCompilationInfo

from rpyyarv import symbols
from rpyyarv.error import RubyException

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOP = os.path.dirname(_HERE)
_BUILD = os.environ.get('RPYYARV_BUILD', os.path.join(_TOP, 'build'))


def _arch_include_dir():
    base = os.path.join(_BUILD, '.ext', 'include')
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            cand = os.path.join(base, name)
            if os.path.exists(os.path.join(cand, 'ruby', 'config.h')):
                return cand
    raise RuntimeError(
        '%s not found. Build CRuby with --enable-shared first:\n'
        '    mkdir build && cd build\n'
        '    ../configure --enable-shared --disable-install-doc && make -j'
        % base)


def _libruby_name():
    for name in sorted(os.listdir(_BUILD)):
        for ext in ('.dylib', '.so'):
            if name.startswith('libruby.') and name.endswith(ext):
                if 'static' in name:
                    continue
                return name[len('lib'):-len(ext)]
    raise RuntimeError('no libruby shared library in %s' % _BUILD)


def _link_extra():
    flags = ['-Wl,-rpath,' + _BUILD]
    if sys.platform == 'darwin':
        # ld bakes in libruby's install prefix; `make relink` rewrites it after
        flags.append('-Wl,-headerpad_max_install_names')
    return flags


eci = ExternalCompilationInfo(
    includes=['ruby.h', 'boot_shim.h'],
    # _TOP and _BUILD carry shape.h and the generated id.h it pulls in.
    include_dirs=[os.path.join(_TOP, 'include'), _arch_include_dir(), _HERE,
                  _TOP, _BUILD],
    separate_module_files=[os.path.join(_HERE, 'boot_shim.c')],
    libraries=[_libruby_name()],
    library_dirs=[_BUILD],
    link_extra=_link_extra(),
)

# VALUE is uintptr_t. Only VALUEs cross this boundary
VALUE = rffi.UINTPTR_T
VALUEP = rffi.CArrayPtr(VALUE)
INTP = rffi.INTP
VOIDP = rffi.VOIDP
MARK_HOOK = lltype.Ptr(lltype.FuncType([], lltype.Void))
CONST_HOOK = lltype.Ptr(lltype.FuncType([], lltype.Void))
BLOCK_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed, rffi.INT, VALUEP],
                                        VALUE))
# (self, mid, argc, argv, blockproc, status, errval) -> result
TRAMP_HOOK = lltype.Ptr(lltype.FuncType(
    [VALUE, VALUE, rffi.INT, VALUEP, VALUE, INTP, VALUEP], VALUE))

MAX_ARGC = 32


def _ext(name, args, result, reenters=False):
    # releasegil=False: all calls hold the GVL; reenters=True on any call that can allocate, so a GC in a callback cannot move objects out from under C locals.
    return rffi.llexternal(name, args, result, compilation_info=eci,
                           releasegil=False,
                           random_effects_on_gcobjs=reenters)


rb_boot = _ext('rpyyarv_boot', [rffi.INT, rffi.CCHARPP, INTP], VOIDP)
rb_cleanup = _ext('rpyyarv_cleanup', [rffi.INT], rffi.INT)
rb_run_node = _ext('rpyyarv_run_node', [VOIDP], rffi.INT, reenters=True)
rb_iseqw_new = _ext('rpyyarv_iseqw_new', [VOIDP], VALUE)
rb_call0 = _ext('rpyyarv_call0', [VALUE, rffi.CCHARP, INTP], VALUE, reenters=True)
rb_str_len = _ext('rpyyarv_str_len', [VALUE], rffi.LONG)
rb_str_ptr = _ext('rpyyarv_str_ptr', [VALUE], rffi.CCHARP)
rb_inspect_cstr = _ext('rpyyarv_inspect_cstr', [VALUE], rffi.CCHARP, reenters=True)
rb_ary_len = _ext('rpyyarv_ary_len', [VALUE], rffi.LONG)
rb_ary_entry = _ext('rpyyarv_ary_entry', [VALUE, rffi.LONG], VALUE, reenters=True)
rb_is_array = _ext('rpyyarv_is_array', [VALUE], rffi.INT)
rb_is_symbol = _ext('rpyyarv_is_symbol', [VALUE], rffi.INT)
rb_is_fixnum = _ext('rpyyarv_is_fixnum', [VALUE], rffi.INT)
rb_is_string = _ext('rpyyarv_is_string', [VALUE], rffi.INT)
rb_is_hash = _ext('rpyyarv_is_hash', [VALUE], rffi.INT)
rb_is_nil = _ext('rpyyarv_is_nil', [VALUE], rffi.INT)
rb_is_true = _ext('rpyyarv_is_true', [VALUE], rffi.INT)
rb_is_false = _ext('rpyyarv_is_false', [VALUE], rffi.INT)
rb_num2long = _ext('rpyyarv_num2long', [VALUE], rffi.LONG, reenters=True)
rb_hash_aref = _ext('rpyyarv_hash_aref', [VALUE, rffi.CCHARP], VALUE, reenters=True)
rb_sym_cstr = _ext('rpyyarv_sym_cstr', [VALUE], rffi.CCHARP, reenters=True)
# No reenters: the codewriter rejects it inside an elidable; safe -- neither this nor rb_shape_iv_index allocates, and elidable calls never survive into an optimized trace.
rb_intern_ = _ext('rpyyarv_intern', [rffi.CCHARP], VALUE)
rb_sym_new = _ext('rpyyarv_sym_new', [rffi.CCHARP], VALUE, reenters=True)
rb_funcallv_id = _ext('rpyyarv_funcallv_id',
                      [VALUE, VALUE, rffi.INT, VALUEP, INTP], VALUE, reenters=True)
rb_funcallv_public_id = _ext('rpyyarv_funcallv_public_id',
                             [VALUE, VALUE, rffi.INT, VALUEP, INTP], VALUE,
                             reenters=True)
rb_top_self = _ext('rpyyarv_top_self', [], VALUE)
rb_int2inum = _ext('rpyyarv_int2inum', [rffi.LONG], VALUE, reenters=True)
rb_float_new = _ext('rpyyarv_float_new', [rffi.DOUBLE], VALUE, reenters=True)
rb_float_layout = _ext('rpyyarv_float_layout', [INTP], lltype.Void)
rb_str_new = _ext('rpyyarv_str_new', [rffi.CCHARP, rffi.LONG], VALUE,
                  reenters=True)
rb_ary_new = _ext('rpyyarv_ary_new', [rffi.INT, VALUEP], VALUE, reenters=True)
rb_str_concat = _ext('rpyyarv_str_concat', [rffi.INT, VALUEP], VALUE, reenters=True)
rb_special_consts = _ext('rpyyarv_special_consts',
                         [VALUEP, VALUEP, VALUEP, VALUEP], lltype.Void)
rb_gc_set_mark_hook = _ext('rpyyarv_gc_set_mark_hook', [MARK_HOOK],
                           lltype.Void)
rb_gc_mark_value = _ext('rpyyarv_gc_mark_value', [VALUE], lltype.Void)
rb_set_const_hook = _ext('rpyyarv_set_const_hook', [CONST_HOOK], lltype.Void)
rb_set_method_hook = _ext('rpyyarv_set_method_hook', [CONST_HOOK], lltype.Void)
rb_gc_start = _ext('rpyyarv_gc_start', [], lltype.Void, reenters=True)
rb_core_classes = _ext('rpyyarv_core_classes', [VALUEP], lltype.Void)
rb_define_class_ = _ext('rpyyarv_define_class',
                        [VALUE, VALUE, VALUE, INTP], VALUE, reenters=True)
rb_define_module_ = _ext('rpyyarv_define_module',
                         [VALUE, VALUE, INTP], VALUE, reenters=True)
rb_class_superclass = _ext('rpyyarv_class_superclass', [VALUE, INTP], VALUE, reenters=True)
rb_singleton_class = _ext('rpyyarv_singleton_class', [VALUE, INTP], VALUE, reenters=True)
rb_obj_alloc = _ext('rpyyarv_obj_alloc', [VALUE, INTP], VALUE, reenters=True)
rb_obj_alloc_fast = _ext('rpyyarv_obj_alloc_fast', [VALUE], VALUE, reenters=True)
rb_const_get_ = _ext('rpyyarv_const_get', [VALUE, VALUE, INTP], VALUE, reenters=True)
rb_const_set_ = _ext('rpyyarv_const_set', [VALUE, VALUE, VALUE, INTP],
                     lltype.Void, reenters=True)
rb_ivar_get_ = _ext('rpyyarv_ivar_get', [VALUE, VALUE, INTP], VALUE, reenters=True)
rb_ivar_set_ = _ext('rpyyarv_ivar_set', [VALUE, VALUE, VALUE, INTP],
                    lltype.Void, reenters=True)
rb_shape_iv_index = _ext('rpyyarv_shape_iv_index',   # no reenters: see rb_intern_
                         [rffi.UINT, VALUE, INTP], rffi.INT)
rb_shape_add_ivar_fits = _ext('rpyyarv_shape_add_ivar_fits',  # no reenters: see rb_intern_
                              [rffi.UINT, rffi.UINT, VALUE, INTP], rffi.INT)
rb_object_layout = _ext('rpyyarv_object_layout', [INTP], lltype.Void)
rb_set_block_callback = _ext('rpyyarv_set_block_callback', [BLOCK_HOOK],
                             lltype.Void)
rb_call_with_block = _ext('rpyyarv_call_with_block',
                          [VALUE, VALUE, rffi.INT, VALUEP, rffi.LONG, INTP],
                          VALUE, reenters=True)
rb_set_trampoline_callback = _ext('rpyyarv_set_trampoline_callback',
                                  [TRAMP_HOOK], lltype.Void)
rb_define_method_id = _ext('rpyyarv_define_method',
                           [VALUE, VALUE, rffi.INT, INTP], lltype.Void,
                           reenters=True)
rb_array_layout = _ext('rpyyarv_array_layout', [INTP], lltype.Void)
rb_ary_resurrect = _ext('rpyyarv_ary_resurrect', [VALUE, INTP], VALUE, reenters=True)
rb_ary_store_ = _ext('rpyyarv_ary_store', [VALUE, rffi.LONG, VALUE, INTP],
                     lltype.Void, reenters=True)
rb_ary_new_capa = _ext('rpyyarv_ary_new_capa', [rffi.LONG, INTP], VALUE, reenters=True)
rb_ary_store_fresh = _ext('rpyyarv_ary_store_fresh', [VALUE, rffi.LONG, VALUE],
                          lltype.Void, reenters=True)
rb_ary_new_capa_fast = _ext('rpyyarv_ary_new_capa_fast', [rffi.LONG], VALUE, reenters=True)
rb_ary_new_filled_fast = _ext('rpyyarv_ary_new_filled_fast', [rffi.LONG, VALUE],
                              VALUE, reenters=True)
rb_ary_new_filled = _ext('rpyyarv_ary_new_filled', [rffi.LONG, VALUE, INTP],
                         VALUE, reenters=True)
rb_ary_cat = _ext('rpyyarv_ary_cat', [VALUE, rffi.INT, VALUEP, INTP],
                  lltype.Void, reenters=True)
rb_range_new_ = _ext('rpyyarv_range_new', [VALUE, VALUE, rffi.INT, INTP],
                     VALUE, reenters=True)
rb_gvar_get_ = _ext('rpyyarv_gvar_get', [rffi.CCHARP, INTP], VALUE, reenters=True)
rb_gvar_set_ = _ext('rpyyarv_gvar_set', [rffi.CCHARP, VALUE, INTP],
                    lltype.Void, reenters=True)
rb_proc_new = _ext('rpyyarv_proc_new', [rffi.LONG, INTP], VALUE, reenters=True)
rb_is_proc = _ext('rpyyarv_is_proc', [VALUE], rffi.INT)
rb_is_class = _ext('rpyyarv_is_class', [VALUE], rffi.INT)
rb_gc_register = _ext('rpyyarv_gc_register_mark_object', [VALUE], lltype.Void, reenters=True)
rb_take_errinfo = _ext('rpyyarv_take_errinfo', [], VALUE)
rb_swap_errinfo = _ext('rpyyarv_swap_errinfo', [VALUE], VALUE)
rb_obj_is_kind_of = _ext('rpyyarv_obj_is_kind_of', [VALUE, VALUE, INTP],
                         rffi.INT, reenters=True)
rb_cleanup_with_error = _ext('rpyyarv_cleanup_with_error', [VALUE], rffi.INT,
                             reenters=True)
rb_hash_new_capa = _ext('rpyyarv_hash_new_capa', [rffi.LONG, INTP], VALUE, reenters=True)
rb_hash_aset_ = _ext('rpyyarv_hash_aset', [VALUE, VALUE, VALUE, INTP],
                     lltype.Void, reenters=True)
rb_hash_resurrect = _ext('rpyyarv_hash_resurrect', [VALUE, INTP], VALUE, reenters=True)
rb_splat_array = _ext('rpyyarv_splat_array', [VALUE, rffi.INT, INTP], VALUE, reenters=True)
rb_vm_core = _ext('rpyyarv_vm_core', [], VALUE, reenters=True)
rb_arity_error = _ext('rpyyarv_arity_error',
                      [rffi.INT, rffi.INT, rffi.INT, INTP], VALUE,
                      reenters=True)
rb_local_jump_error = _ext('rpyyarv_local_jump_error',
                           [rffi.CCHARP, VALUE, rffi.INT, INTP], VALUE,
                           reenters=True)
rb_set_block_unwind = _ext('rpyyarv_set_block_unwind', [], lltype.Void)
rb_bop_mask = _ext('rpyyarv_bop_mask', [], VALUE, reenters=True)
rb_require_resolve = _ext('rpyyarv_require_resolve', [VALUE, VALUEP, INTP],
                          rffi.INT, reenters=True)
rb_provide_ = _ext('rpyyarv_provide', [VALUE, INTP], lltype.Void,
                   reenters=True)
rb_absolute_path = _ext('rpyyarv_absolute_path', [VALUE, VALUE, INTP], VALUE,
                        reenters=True)
rb_method_owner = _ext('rpyyarv_method_owner', [VALUE, VALUE], VALUE,
                       reenters=True)
rb_super_owner = _ext('rpyyarv_super_owner', [VALUE, VALUE, VALUE], VALUE,
                      reenters=True)
# No reenters: reads two struct fields after a type test, allocating nothing.
rb_range_part = _ext('rpyyarv_range_part', [VALUE, rffi.INT], VALUE)
# No reenters: the barrier sets bits in preallocated page bitmaps and reaches no mark callback; see the comment on rpyyarv_obj_written.
rb_obj_written = _ext('rpyyarv_obj_written', [VALUE, VALUE], lltype.Void)
rb_wb_direct = _ext('rpyyarv_wb_direct', [], rffi.INT)

REQ_LOADED = 0
REQ_RB = 1
REQ_FOREIGN = 2

NCLASS = 14


def _v(n):
    return rffi.cast(VALUE, n)


# One preallocated cell per shim nesting level; a CRuby call can trampoline back into RPyYARV, so these really do nest.
SHIM_DEPTH = 64

_status_pool = lltype.malloc(INTP.TO, SHIM_DEPTH, flavor='raw',
                             immortal=True, zero=True)
_argv_pool = lltype.malloc(rffi.CArray(VALUE), SHIM_DEPTH * (MAX_ARGC + 1),
                           flavor='raw', immortal=True, zero=True)


class _Nesting(object):
    def __init__(self):
        self.status = 0
        self.argv = 0


_nesting = _Nesting()


def _enter_status():
    """The status cell for one shim call; past SHIM_DEPTH it falls back to a fresh raw cell rather than reusing a slot."""
    d = _nesting.status
    _nesting.status = d + 1
    if d >= SHIM_DEPTH:
        p = lltype.malloc(INTP.TO, 1, flavor='raw')
    else:
        p = rffi.ptradd(_status_pool, d)
    p[0] = rffi.cast(rffi.INT, 0)
    return p


def _leave_status(p):
    d = _nesting.status - 1
    _nesting.status = d
    failed = rffi.cast(lltype.Signed, p[0]) != 0
    if d >= SHIM_DEPTH:
        lltype.free(p, flavor='raw')
    return failed


def _enter_argv(n):
    """An argument buffer for one shim call; the shim copies it to the machine stack before anything can allocate, so this one need not be scanned."""
    assert n <= MAX_ARGC
    d = _nesting.argv
    _nesting.argv = d + 1
    if d >= SHIM_DEPTH:
        return lltype.malloc(rffi.CArray(VALUE), n + 1, flavor='raw')
    return rffi.ptradd(_argv_pool, d * (MAX_ARGC + 1))


def _leave_argv(p):
    d = _nesting.argv - 1
    _nesting.argv = d
    if d >= SHIM_DEPTH:
        lltype.free(p, flavor='raw')


class RubyError(Exception):
    # A call RPyYARV could not make; one that raised becomes a RubyException.
    def __init__(self, mid):
        self.mid = mid


def _failed(name):
    v = rffi.cast(lltype.Signed, rb_take_errinfo())
    raise RubyException(v, name)


def _failed_mid(mid):
    """As _failed, but off the send path, where resolving the name costs a dict lookup on every call that does not raise."""
    _failed(symbols.name_of(mid))


def call0(recv, mid):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        with rffi.scoped_str2charp(mid) as c_mid:
            v = rb_call0(_v(recv), c_mid, state)
        if rffi.cast(lltype.Signed, state[0]) != 0:
            raise RubyError(mid)
        return rffi.cast(lltype.Signed, v)


def inspect(v):
    p = rb_inspect_cstr(_v(v))
    if not p:
        return '<inspect failed>'
    return rffi.charp2str(p)


def is_array(v):
    return rffi.cast(lltype.Signed, rb_is_array(_v(v))) != 0


def is_symbol(v):
    return rffi.cast(lltype.Signed, rb_is_symbol(_v(v))) != 0


def is_fixnum(v):
    return rffi.cast(lltype.Signed, rb_is_fixnum(_v(v))) != 0


def is_string(v):
    return rffi.cast(lltype.Signed, rb_is_string(_v(v))) != 0


def is_hash(v):
    return rffi.cast(lltype.Signed, rb_is_hash(_v(v))) != 0


def is_nil(v):
    return rffi.cast(lltype.Signed, rb_is_nil(_v(v))) != 0


def is_true(v):
    return rffi.cast(lltype.Signed, rb_is_true(_v(v))) != 0


def is_false(v):
    return rffi.cast(lltype.Signed, rb_is_false(_v(v))) != 0


def num2long(v):
    return rffi.cast(lltype.Signed, rb_num2long(_v(v)))


def ary_len(v):
    return rffi.cast(lltype.Signed, rb_ary_len(_v(v)))


def ary_entry(v, i):
    return rffi.cast(lltype.Signed,
                     rb_ary_entry(_v(v), rffi.cast(rffi.LONG, i)))


def hash_aref(hash_v, key):
    with rffi.scoped_str2charp(key) as c_key:
        return rffi.cast(lltype.Signed, rb_hash_aref(_v(hash_v), c_key))


def str_of(v):
    # Length-based read: rb_string_value_cstr raises on an embedded NUL, and that longjmp would cross the RPython frame unprotected.
    n = rffi.cast(lltype.Signed, rb_str_len(_v(v)))
    if n < 0:
        raise RubyError('to_s')
    return rffi.charpsize2str(rb_str_ptr(_v(v)), n)


def sym_of(v):
    p = rb_sym_cstr(_v(v))
    if not p:
        raise RubyError('id2name')
    return rffi.charp2str(p)


def intern(name):
    with rffi.scoped_str2charp(name) as c_name:
        return rffi.cast(lltype.Signed, rb_intern_(c_name))


def sym_new(name):
    with rffi.scoped_str2charp(name) as c_name:
        return rffi.cast(lltype.Signed, rb_sym_new(c_name))


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


def ary_new(values):
    n = len(values)
    if n > MAX_ARGC:
        return _ary_new_chunked(values)
    buf = _enter_argv(n)
    i = 0
    while i < n:
        buf[i] = rffi.cast(VALUE, values[i])
        i += 1
    ret = rffi.cast(lltype.Signed, rb_ary_new(rffi.cast(rffi.INT, n), buf))
    _leave_argv(buf)
    return ret


def _ary_new_chunked(values):
    """`ary` stays an RPython local, which the conservative stack scan covers between chunks."""
    n = len(values)
    ary = 0
    state = _enter_status()
    ary = rffi.cast(lltype.Signed,
                    rb_ary_new_capa(rffi.cast(rffi.LONG, n), state))
    failed = _leave_status(state)
    if failed:
        _failed('Array.new')
    at = 0
    while at < n:
        count = n - at
        if count > MAX_ARGC:
            count = MAX_ARGC
        with lltype.scoped_alloc(rffi.CArray(VALUE), count + 1) as buf:
            i = 0
            while i < count:
                buf[i] = rffi.cast(VALUE, values[at + i])
                i += 1
            state = _enter_status()
            rb_ary_cat(rffi.cast(VALUE, ary), rffi.cast(rffi.INT, count),
                       buf, state)
            failed = _leave_status(state)
        if failed:
            _failed('Array#concat')
        at += count
    return ary


def call_with_block(recv, rid, args, handle, mid):
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
                           rffi.cast(rffi.LONG, handle), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def install_block_callback(fn):
    """A plain function, not an llhelper pointer: only then does rffi build the enter-RPython-from-C wrapper."""
    rb_set_block_callback(fn)


def install_trampoline_callback(fn):
    """As install_block_callback: a plain function, so rffi builds the enter-RPython-from-C wrapper for it."""
    rb_set_trampoline_callback(fn)


def define_method_entry(klass, rid, private):
    """A CRuby method entry over the generic trampoline."""
    state = _enter_status()
    rb_define_method_id(_v(klass), _v(rid),
                        rffi.cast(rffi.INT, 1 if private else 0), state)
    failed = _leave_status(state)
    if failed:
        _failed('define_method')


def as_signed(v):
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


def as_value(n):
    return rffi.cast(VALUE, n)


def ary_resurrect(ary):
    state = _enter_status()
    v = rb_ary_resurrect(_v(ary), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array#dup')
    return ret


def ary_store(ary, idx, val):
    state = _enter_status()
    rb_ary_store_(_v(ary), rffi.cast(rffi.LONG, idx), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('Array#[]=')


def ary_store_fresh(ary, idx, val):
    """No status cell: the shim call cannot raise, so there is nothing to report."""
    rb_ary_store_fresh(_v(ary), rffi.cast(rffi.LONG, idx), _v(val))


def ary_new_capa_fast(capa):
    return rffi.cast(lltype.Signed, rb_ary_new_capa_fast(rffi.cast(rffi.LONG, capa)))


def ary_new_filled_fast(n, val):
    return rffi.cast(lltype.Signed,
                     rb_ary_new_filled_fast(rffi.cast(rffi.LONG, n), _v(val)))


def ary_new_capa(capa):
    state = _enter_status()
    v = rb_ary_new_capa(rffi.cast(rffi.LONG, capa), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array.new')
    return ret


def ary_new_filled(n, val):
    state = _enter_status()
    v = rb_ary_new_filled(rffi.cast(rffi.LONG, n), _v(val), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array.new')
    return ret


def range_new(low, high, excl):
    state = _enter_status()
    v = rb_range_new_(_v(low), _v(high), rffi.cast(rffi.INT, excl), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Range.new')
    return ret


def gvar_get(name):
    state = _enter_status()
    with rffi.scoped_str2charp(name) as c_name:
        v = rb_gvar_get_(c_name, state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed(name)
    return ret


def gvar_set(name, val):
    state = _enter_status()
    with rffi.scoped_str2charp(name) as c_name:
        rb_gvar_set_(c_name, _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed(name)


def str_concat(parts):
    n = len(parts)
    if n > MAX_ARGC:
        raise RubyError('String#concat')
    with lltype.scoped_alloc(rffi.CArray(VALUE), n + 1) as buf:
        i = 0
        while i < n:
            buf[i] = rffi.cast(VALUE, parts[i])
            i += 1
        return rffi.cast(lltype.Signed,
                         rb_str_concat(rffi.cast(rffi.INT, n), buf))


def top_self():
    return rffi.cast(lltype.Signed, rb_top_self())


def int2inum(n):
    return rffi.cast(lltype.Signed, rb_int2inum(rffi.cast(rffi.LONG, n)))


def float_new(d):
    return rffi.cast(lltype.Signed, rb_float_new(rffi.cast(rffi.DOUBLE, d)))


def str_new(s):
    # Length-carrying, so a literal holding NUL bytes survives the round trip.
    with rffi.scoped_str2charp(s) as c_s:
        return rffi.cast(lltype.Signed, rb_str_new(c_s, len(s)))


def special_consts():
    """(Qfalse, Qnil, Qtrue, FIXNUM_FLAG) as this libruby defines them."""
    with lltype.scoped_alloc(rffi.CArray(VALUE), 4) as out:
        rb_special_consts(rffi.ptradd(out, 0), rffi.ptradd(out, 1),
                          rffi.ptradd(out, 2), rffi.ptradd(out, 3))
        return (rffi.cast(lltype.Signed, out[0]),
                rffi.cast(lltype.Signed, out[1]),
                rffi.cast(lltype.Signed, out[2]),
                rffi.cast(lltype.Signed, out[3]))


def core_classes():
    with lltype.scoped_alloc(rffi.CArray(VALUE), NCLASS) as out:
        rb_core_classes(out)
        result = [0] * NCLASS
        i = 0
        while i < NCLASS:
            result[i] = rffi.cast(lltype.Signed, out[i])
            i += 1
        return result


def obj_written(a, b):
    return rb_obj_written(_v(a), _v(b))


def wb_direct():
    return rffi.cast(lltype.Signed, rb_wb_direct()) != 0


RANGE_BEG = 0
RANGE_END = 1
RANGE_EXCL = 2


def range_part(v, which):
    """One Range field, or Qundef when v is not a direct Range."""
    return rffi.cast(lltype.Signed,
                     rb_range_part(_v(v), rffi.cast(rffi.INT, which)))


def method_owner(klass, rid):
    """The module klass resolves rid through, or Qnil when it has none."""
    return rffi.cast(lltype.Signed, rb_method_owner(_v(klass), _v(rid)))


def super_owner(klass, owner, rid):
    """The module `super` from owner's copy of rid reaches next, or Qnil when there is none."""
    return rffi.cast(lltype.Signed,
                     rb_super_owner(_v(klass), _v(owner), _v(rid)))


def define_class(cbase, rid, super_v):
    state = _enter_status()
    v = rb_define_class_(_v(cbase), _v(rid), _v(super_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Class.new')
    return ret


def define_module(cbase, rid):
    state = _enter_status()
    v = rb_define_module_(_v(cbase), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Module.new')
    return ret


def class_superclass(klass):
    state = _enter_status()
    v = rb_class_superclass(_v(klass), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        rb_take_errinfo()
        return 0
    return ret


def singleton_class(obj):
    state = _enter_status()
    v = rb_singleton_class(_v(obj), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('singleton_class')
    return ret


def obj_alloc_fast(klass):
    return rffi.cast(lltype.Signed, rb_obj_alloc_fast(_v(klass)))


def obj_alloc(klass):
    state = _enter_status()
    v = rb_obj_alloc(_v(klass), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('allocate')
    return ret


def const_get(klass, rid):
    state = _enter_status()
    v = rb_const_get_(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('const_get')
    return ret


def const_set(klass, rid, val):
    state = _enter_status()
    rb_const_set_(_v(klass), _v(rid), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('const_set')


def ivar_get(obj, rid):
    state = _enter_status()
    v = rb_ivar_get_(_v(obj), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('instance_variable_get')
    return ret


def ivar_set(obj, rid, val):
    state = _enter_status()
    rb_ivar_set_(_v(obj), _v(rid), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('instance_variable_set')


LAYOUT_N = 12


def object_layout():
    out = [0] * LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, LAYOUT_N) as buf:
        rb_object_layout(buf)
        for i in range(LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


FLOAT_LAYOUT_N = 3


def float_layout():
    out = [0] * FLOAT_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, FLOAT_LAYOUT_N) as buf:
        rb_float_layout(buf)
        for i in range(FLOAT_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


ARRAY_LAYOUT_N = 8


def array_layout():
    out = [0] * ARRAY_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, ARRAY_LAYOUT_N) as buf:
        rb_array_layout(buf)
        for i in range(ARRAY_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


def shape_iv_index(shape_id, rid):
    """The field slot holding rid in shape_id: >= 0 found, -1 provably absent, -2 fast path unusable."""
    with lltype.scoped_alloc(INTP.TO, 1) as idx:
        idx[0] = rffi.cast(rffi.INT, -1)
        found = rffi.cast(lltype.Signed,
                          rb_shape_iv_index(rffi.cast(rffi.UINT, shape_id),
                                            _v(rid), idx))
        slot = rffi.cast(lltype.Signed, idx[0])
    if found == 1:
        return slot
    if found == 0:
        return -1
    return -2


def shape_add_ivar_slot(before, after, rid):
    """The slot a raw store may put rid in when it moves an object from before to after, or -1 when only rb_ivar_set may."""
    with lltype.scoped_alloc(INTP.TO, 1) as idx:
        idx[0] = rffi.cast(rffi.INT, -1)
        ok = rffi.cast(lltype.Signed,
                       rb_shape_add_ivar_fits(rffi.cast(rffi.UINT, before),
                                              rffi.cast(rffi.UINT, after),
                                              _v(rid), idx))
        slot = rffi.cast(lltype.Signed, idx[0])
    if ok == 1:
        return slot
    return -1


def proc_new(handle):
    """A Proc whose call re-enters RPyYARV through the block callback."""
    state = _enter_status()
    v = rb_proc_new(rffi.cast(rffi.LONG, handle), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Proc.new')
    return ret


def is_proc(v):
    return rffi.cast(lltype.Signed, rb_is_proc(_v(v))) != 0


def is_class(v):
    return rffi.cast(lltype.Signed, rb_is_class(_v(v))) != 0


def obj_is_kind_of(obj, klass):
    state = _enter_status()
    r = rffi.cast(lltype.Signed, rb_obj_is_kind_of(_v(obj), _v(klass),
                                                   state))
    failed = _leave_status(state)
    if failed:
        _failed('kind_of?')
    return r != 0


def swap_errinfo(v):
    return rffi.cast(lltype.Signed, rb_swap_errinfo(_v(v)))


def cleanup_with_error(v):
    return rffi.cast(lltype.Signed, rb_cleanup_with_error(_v(v)))


def hash_new(capa):
    state = _enter_status()
    v = rb_hash_new_capa(rffi.cast(rffi.LONG, capa), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash.new')
    return ret


def hash_aset(hash_v, key, val):
    state = _enter_status()
    rb_hash_aset_(_v(hash_v), _v(key), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('Hash#[]=')


def hash_resurrect(hash_v):
    state = _enter_status()
    v = rb_hash_resurrect(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#dup')
    return ret


def splat_array(ary, flag):
    state = _enter_status()
    v = rb_splat_array(_v(ary), rffi.cast(rffi.INT, flag), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('to_a')
    return ret


def vm_core():
    return rffi.cast(lltype.Signed, rb_vm_core())


def arity_error(given, min_argc, max_argc):
    """The ArgumentError VALUE; -1 for max_argc means unlimited."""
    state = _enter_status()
    v = rb_arity_error(rffi.cast(rffi.INT, given),
                       rffi.cast(rffi.INT, min_argc),
                       rffi.cast(rffi.INT, max_argc), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('ArgumentError')
    return ret


def local_jump_error(mesg, val, reason):
    """The LocalJumpError VALUE; reason is a ruby_tag_type."""
    state = _enter_status()
    with rffi.scoped_str2charp(mesg) as c_mesg:
        v = rb_local_jump_error(c_mesg, _v(val),
                                rffi.cast(rffi.INT, reason), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('LocalJumpError')
    return ret


def set_block_unwind():
    """Tell the shim the block it is running left early; see boot_shim.h."""
    rb_set_block_unwind()


BOP_COUNT_SHIFT = 32


def bop_mask():
    """(pair count, one bit per redefined pair) as the shim orders them."""
    v = rffi.cast(lltype.Signed, rb_bop_mask())
    return v >> BOP_COUNT_SHIFT, v & ((1 << BOP_COUNT_SHIFT) - 1)


def require_resolve(fname):
    """(REQ_*, expanded path VALUE); the path is 0 unless the answer is REQ_RB."""
    path = 0
    kind = REQ_FOREIGN
    with lltype.scoped_alloc(rffi.CArray(VALUE), 1) as out:
        out[0] = rffi.cast(VALUE, 0)
        with lltype.scoped_alloc(INTP.TO, 1) as state:
            state[0] = rffi.cast(rffi.INT, 0)
            kind = rffi.cast(lltype.Signed,
                             rb_require_resolve(_v(fname), out, state))
        path = rffi.cast(lltype.Signed, out[0])
    if kind != REQ_RB:
        return kind, 0
    return kind, path


def provide(path):
    state = _enter_status()
    rb_provide_(_v(path), state)
    failed = _leave_status(state)
    if failed:
        _failed('$LOADED_FEATURES')


def absolute_path(fname, base):
    state = _enter_status()
    v = rb_absolute_path(_v(fname), _v(base), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('File.absolute_path')
    return ret


def gc_register(v):
    rb_gc_register(_v(v))


def gc_mark_value(v):
    rb_gc_mark_value(rffi.cast(VALUE, v))


def gc_start():
    rb_gc_start()


def set_mark_hook(fn):
    rb_gc_set_mark_hook(fn)


def set_const_hook(fn):
    """As install_block_callback: a plain function, so rffi builds the enter-RPython-from-C wrapper for it."""
    rb_set_const_hook(fn)


def set_method_hook(fn):
    rb_set_method_hook(fn)


class _Node(object):
    # The compiled main script, kept so run_node() can hand it back to CRuby.
    def __init__(self):
        self.ptr = lltype.nullptr(VOIDP.TO)


node = _Node()


def boot(argv):
    """Return (iseqw, status). iseqw is 0 when there is no ISeq to run."""
    # Never freed: ruby_sysinit keeps this pointer in origarg (ruby.c) for the process lifetime.
    c_argv = rffi.liststr2charpp(argv)
    with lltype.scoped_alloc(INTP.TO, 1) as status:
        status[0] = rffi.cast(rffi.INT, 0)
        n = rb_boot(rffi.cast(rffi.INT, len(argv)), c_argv, status)
        if not n:
            return 0, rffi.cast(lltype.Signed, status[0])
        node.ptr = n
        return rffi.cast(lltype.Signed, rb_iseqw_new(n)), 0


def run_node():
    """Runs the script and cleans up; the answer is the process exit status."""
    return rffi.cast(lltype.Signed, rb_run_node(node.ptr))


def cleanup(status):
    return rffi.cast(lltype.Signed, rb_cleanup(rffi.cast(rffi.INT, status)))
