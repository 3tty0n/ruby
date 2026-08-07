"""CRuby boot and ISeq handoff
"""

import os
import sys

from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.translator.tool.cbuild import ExternalCompilationInfo

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
BLOCK_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed, rffi.INT, VALUEP],
                                        VALUE))

# RPython side a VALUE is a plain signed word: FIX2LONG is an arithmetic
# right shift, which only a signed type gets right.
MAX_ARGC = 32


def _ext(name, args, result, reenters=False):
    # releasegil=False: every call runs on the main Ruby thread holding the
    # GVL, and the mark hook re-enters RPython from inside one of them.
    #
    # reenters=True marks a call that runs RPython code again through a
    # callback: without it the root walker would keep live RPython objects
    # only in C locals across the call, and a minor collection inside the
    # callback would move them out from under it.
    return rffi.llexternal(name, args, result, compilation_info=eci,
                           releasegil=False,
                           random_effects_on_gcobjs=reenters)


rb_boot = _ext('rpyyarv_boot', [rffi.INT, rffi.CCHARPP, INTP], VOIDP)
rb_cleanup = _ext('rpyyarv_cleanup', [rffi.INT], rffi.INT)
rb_iseqw_new = _ext('rpyyarv_iseqw_new', [VOIDP], VALUE)
rb_call0 = _ext('rpyyarv_call0', [VALUE, rffi.CCHARP, INTP], VALUE)
rb_cstr = _ext('rpyyarv_cstr', [VALUE], rffi.CCHARP)
rb_inspect_cstr = _ext('rpyyarv_inspect_cstr', [VALUE], rffi.CCHARP)
rb_ary_len = _ext('rpyyarv_ary_len', [VALUE], rffi.LONG)
rb_ary_entry = _ext('rpyyarv_ary_entry', [VALUE, rffi.LONG], VALUE)
rb_is_array = _ext('rpyyarv_is_array', [VALUE], rffi.INT)
rb_is_symbol = _ext('rpyyarv_is_symbol', [VALUE], rffi.INT)
rb_is_fixnum = _ext('rpyyarv_is_fixnum', [VALUE], rffi.INT)
rb_is_string = _ext('rpyyarv_is_string', [VALUE], rffi.INT)
rb_is_hash = _ext('rpyyarv_is_hash', [VALUE], rffi.INT)
rb_is_nil = _ext('rpyyarv_is_nil', [VALUE], rffi.INT)
rb_is_true = _ext('rpyyarv_is_true', [VALUE], rffi.INT)
rb_is_false = _ext('rpyyarv_is_false', [VALUE], rffi.INT)
rb_num2long = _ext('rpyyarv_num2long', [VALUE], rffi.LONG)
rb_hash_aref = _ext('rpyyarv_hash_aref', [VALUE, rffi.CCHARP], VALUE)
rb_sym_cstr = _ext('rpyyarv_sym_cstr', [VALUE], rffi.CCHARP)
rb_intern_ = _ext('rpyyarv_intern', [rffi.CCHARP], VALUE)
rb_sym_new = _ext('rpyyarv_sym_new', [rffi.CCHARP], VALUE)
rb_funcallv_id = _ext('rpyyarv_funcallv_id',
                      [VALUE, VALUE, rffi.INT, VALUEP, INTP], VALUE)
rb_top_self = _ext('rpyyarv_top_self', [], VALUE)
rb_int2inum = _ext('rpyyarv_int2inum', [rffi.LONG], VALUE)
rb_str_new = _ext('rpyyarv_str_new', [rffi.CCHARP], VALUE)
rb_ary_new = _ext('rpyyarv_ary_new', [rffi.INT, VALUEP], VALUE)
rb_str_concat = _ext('rpyyarv_str_concat', [rffi.INT, VALUEP], VALUE)
rb_special_consts = _ext('rpyyarv_special_consts',
                         [VALUEP, VALUEP, VALUEP, VALUEP], lltype.Void)
rb_gc_set_mark_hook = _ext('rpyyarv_gc_set_mark_hook', [MARK_HOOK],
                           lltype.Void)
rb_gc_mark_value = _ext('rpyyarv_gc_mark_value', [VALUE], lltype.Void)
rb_gc_start = _ext('rpyyarv_gc_start', [], lltype.Void)
rb_core_classes = _ext('rpyyarv_core_classes', [VALUEP], lltype.Void)
rb_define_class_ = _ext('rpyyarv_define_class',
                        [VALUE, VALUE, VALUE, INTP], VALUE)
rb_class_superclass = _ext('rpyyarv_class_superclass', [VALUE, INTP], VALUE)
rb_obj_alloc = _ext('rpyyarv_obj_alloc', [VALUE, INTP], VALUE)
rb_const_get_ = _ext('rpyyarv_const_get', [VALUE, VALUE, INTP], VALUE)
rb_const_set_ = _ext('rpyyarv_const_set', [VALUE, VALUE, VALUE, INTP],
                     lltype.Void)
rb_ivar_get_ = _ext('rpyyarv_ivar_get', [VALUE, VALUE, INTP], VALUE)
rb_ivar_set_ = _ext('rpyyarv_ivar_set', [VALUE, VALUE, VALUE, INTP],
                    lltype.Void)
rb_shape_iv_index = _ext('rpyyarv_shape_iv_index',
                         [rffi.UINT, VALUE, INTP], rffi.INT)
rb_object_layout = _ext('rpyyarv_object_layout', [INTP], lltype.Void)
rb_set_block_callback = _ext('rpyyarv_set_block_callback', [BLOCK_HOOK],
                             lltype.Void)
rb_call_with_block = _ext('rpyyarv_call_with_block',
                          [VALUE, VALUE, rffi.INT, VALUEP, rffi.LONG, INTP],
                          VALUE, reenters=True)
rb_array_layout = _ext('rpyyarv_array_layout', [INTP], lltype.Void)
rb_ary_resurrect = _ext('rpyyarv_ary_resurrect', [VALUE, INTP], VALUE)
rb_ary_store_ = _ext('rpyyarv_ary_store', [VALUE, rffi.LONG, VALUE, INTP],
                     lltype.Void)
rb_ary_new_capa = _ext('rpyyarv_ary_new_capa', [rffi.LONG, INTP], VALUE)
rb_ary_cat = _ext('rpyyarv_ary_cat', [VALUE, rffi.INT, VALUEP, INTP],
                  lltype.Void)
rb_range_new_ = _ext('rpyyarv_range_new', [VALUE, VALUE, rffi.INT, INTP],
                     VALUE)
rb_gvar_get_ = _ext('rpyyarv_gvar_get', [rffi.CCHARP, INTP], VALUE)
rb_gvar_set_ = _ext('rpyyarv_gvar_set', [rffi.CCHARP, VALUE, INTP],
                    lltype.Void)
rb_is_class = _ext('rpyyarv_is_class', [VALUE], rffi.INT)
rb_gc_register = _ext('rpyyarv_gc_register_mark_object', [VALUE], lltype.Void)

NCLASS = 12


def _v(n):
    """Signed RPython word -> uintptr_t VALUE for the C boundary."""
    return rffi.cast(VALUE, n)


class RubyError(Exception):
    def __init__(self, mid):
        self.mid = mid


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
    p = rb_cstr(_v(v))
    if not p:
        raise RubyError('to_s')
    return rffi.charp2str(p)


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


def funcallv(recv, rid, args, name):
    """rb_funcallv on signed VALUEs; RubyError when the callee raised."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(name)
    ret = 0
    failed = False
    with lltype.scoped_alloc(rffi.CArray(VALUE), argc + 1) as argv:
        i = 0
        while i < argc:
            argv[i] = rffi.cast(VALUE, args[i])
            i += 1
        with lltype.scoped_alloc(INTP.TO, 1) as state:
            state[0] = rffi.cast(rffi.INT, 0)
            v = rb_funcallv_id(rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
                               rffi.cast(rffi.INT, argc), argv, state)
            failed = rffi.cast(lltype.Signed, state[0]) != 0
            ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError(name)
    return ret


def ary_new(values):
    n = len(values)
    if n > MAX_ARGC:
        return _ary_new_chunked(values)
    with lltype.scoped_alloc(rffi.CArray(VALUE), n + 1) as buf:
        i = 0
        while i < n:
            buf[i] = rffi.cast(VALUE, values[i])
            i += 1
        return rffi.cast(lltype.Signed,
                         rb_ary_new(rffi.cast(rffi.INT, n), buf))


def _ary_new_chunked(values):
    """More elements than one machine-stack buffer holds. `ary` stays an
    RPython local, so the conservative stack scan covers it between chunks;
    the elements themselves are still in the caller's marked frame."""
    n = len(values)
    ary = 0
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        ary = rffi.cast(lltype.Signed,
                        rb_ary_new_capa(rffi.cast(rffi.LONG, n), state))
        failed = rffi.cast(lltype.Signed, state[0]) != 0
    if failed:
        raise RubyError('Array.new')
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
            with lltype.scoped_alloc(INTP.TO, 1) as state:
                state[0] = rffi.cast(rffi.INT, 0)
                rb_ary_cat(rffi.cast(VALUE, ary), rffi.cast(rffi.INT, count),
                           buf, state)
                failed = rffi.cast(lltype.Signed, state[0]) != 0
        if failed:
            raise RubyError('Array#concat')
        at += count
    return ary


def call_with_block(recv, rid, args, handle, name):
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(name)
    ret = 0
    failed = False
    with lltype.scoped_alloc(rffi.CArray(VALUE), argc + 1) as argv:
        i = 0
        while i < argc:
            argv[i] = rffi.cast(VALUE, args[i])
            i += 1
        with lltype.scoped_alloc(INTP.TO, 1) as state:
            state[0] = rffi.cast(rffi.INT, 0)
            v = rb_call_with_block(_v(recv), _v(rid),
                                   rffi.cast(rffi.INT, argc), argv,
                                   rffi.cast(rffi.LONG, handle), state)
            failed = rffi.cast(lltype.Signed, state[0]) != 0
            ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError(name)
    return ret


def install_block_callback(fn):
    """Deliberately a plain function, not an llhelper pointer: rffi only
    builds the enter-RPython-from-C wrapper (gc_stack_bottom, exception
    guard) when the callback crosses as a function."""
    rb_set_block_callback(fn)


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
    """A signed RPython word back out to C as a VALUE."""
    return rffi.cast(VALUE, n)


def ary_resurrect(ary):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        v = rb_ary_resurrect(_v(ary), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError('Array#dup')
    return ret


def ary_store(ary, idx, val):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        rb_ary_store_(_v(ary), rffi.cast(rffi.LONG, idx), _v(val), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
    if failed:
        raise RubyError('Array#[]=')


def range_new(low, high, excl):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        v = rb_range_new_(_v(low), _v(high), rffi.cast(rffi.INT, excl), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError('Range.new')
    return ret


def gvar_get(name):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        with rffi.scoped_str2charp(name) as c_name:
            v = rb_gvar_get_(c_name, state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError(name)
    return ret


def gvar_set(name, val):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        with rffi.scoped_str2charp(name) as c_name:
            rb_gvar_set_(c_name, _v(val), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
    if failed:
        raise RubyError(name)


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


def str_new(s):
    with rffi.scoped_str2charp(s) as c_s:
        return rffi.cast(lltype.Signed, rb_str_new(c_s))


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


def define_class(cbase, rid, super_v):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        v = rb_define_class_(_v(cbase), _v(rid), _v(super_v), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError('Class.new')
    return ret


def class_superclass(klass):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        v = rb_class_superclass(_v(klass), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        return 0
    return ret


def obj_alloc(klass):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        v = rb_obj_alloc(_v(klass), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError('allocate')
    return ret


def const_get(klass, rid):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        v = rb_const_get_(_v(klass), _v(rid), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError('const_get')
    return ret


def const_set(klass, rid, val):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        rb_const_set_(_v(klass), _v(rid), _v(val), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
    if failed:
        raise RubyError('const_set')


def ivar_get(obj, rid):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        v = rb_ivar_get_(_v(obj), _v(rid), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
        ret = rffi.cast(lltype.Signed, v)
    if failed:
        raise RubyError('instance_variable_get')
    return ret


def ivar_set(obj, rid, val):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        rb_ivar_set_(_v(obj), _v(rid), _v(val), state)
        failed = rffi.cast(lltype.Signed, state[0]) != 0
    if failed:
        raise RubyError('instance_variable_set')


LAYOUT_N = 6


def object_layout():
    out = [0] * LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, LAYOUT_N) as buf:
        rb_object_layout(buf)
        for i in range(LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


ARRAY_LAYOUT_N = 6


def array_layout():
    out = [0] * ARRAY_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, ARRAY_LAYOUT_N) as buf:
        rb_array_layout(buf)
        for i in range(ARRAY_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


def shape_iv_index(shape_id, rid):
    """The field slot holding rid in shape_id: >= 0 found, -1 provably absent,
    -2 when the fast path must not be used."""
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


def is_class(v):
    return rffi.cast(lltype.Signed, rb_is_class(_v(v))) != 0


def gc_register(v):
    rb_gc_register(_v(v))


def gc_mark_value(v):
    rb_gc_mark_value(rffi.cast(VALUE, v))


def gc_start():
    rb_gc_start()


def set_mark_hook(fn):
    rb_gc_set_mark_hook(fn)


def boot(argv):
    """Return (iseqw, status). iseqw is 0 when there is no ISeq to run."""
    # Never freed: ruby_sysinit stores this pointer in origarg (ruby.c)
    # and uses it for the process lifetime ($0, dladdr checks).
    c_argv = rffi.liststr2charpp(argv)
    with lltype.scoped_alloc(INTP.TO, 1) as status:
        status[0] = rffi.cast(rffi.INT, 0)
        n = rb_boot(rffi.cast(rffi.INT, len(argv)), c_argv, status)
        if not n:
            return 0, rffi.cast(lltype.Signed, status[0])
        return rffi.cast(lltype.Signed, rb_iseqw_new(n)), 0


def cleanup(status):
    return rffi.cast(lltype.Signed, rb_cleanup(rffi.cast(rffi.INT, status)))
