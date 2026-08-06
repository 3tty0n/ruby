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
    include_dirs=[os.path.join(_TOP, 'include'), _arch_include_dir(), _HERE],
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

# RPython side a VALUE is a plain signed word: FIX2LONG is an arithmetic
# right shift, which only a signed type gets right.
MAX_ARGC = 32


def _ext(name, args, result):
    # releasegil=False: every call runs on the main Ruby thread holding the
    # GVL, and the mark hook re-enters RPython from inside one of them.
    return rffi.llexternal(name, args, result, compilation_info=eci,
                           releasegil=False)


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
        raise RubyError('Array')
    with lltype.scoped_alloc(rffi.CArray(VALUE), n + 1) as buf:
        i = 0
        while i < n:
            buf[i] = rffi.cast(VALUE, values[i])
            i += 1
        return rffi.cast(lltype.Signed,
                         rb_ary_new(rffi.cast(rffi.INT, n), buf))


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
