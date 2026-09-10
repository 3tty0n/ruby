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
INTP = rffi.INTP
VOIDP = rffi.VOIDP


def _ext(name, args, result):
    return rffi.llexternal(name, args, result, compilation_info=eci)


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


class RubyError(Exception):
    def __init__(self, mid):
        self.mid = mid


def call0(recv, mid):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        with rffi.scoped_str2charp(mid) as c_mid:
            v = rb_call0(recv, c_mid, state)
        if rffi.cast(lltype.Signed, state[0]) != 0:
            raise RubyError(mid)
        return v


def inspect(v):
    p = rb_inspect_cstr(v)
    if not p:
        return '<inspect failed>'
    return rffi.charp2str(p)


def is_array(v):
    return rffi.cast(lltype.Signed, rb_is_array(v)) != 0


def is_symbol(v):
    return rffi.cast(lltype.Signed, rb_is_symbol(v)) != 0


def is_fixnum(v):
    return rffi.cast(lltype.Signed, rb_is_fixnum(v)) != 0


def is_string(v):
    return rffi.cast(lltype.Signed, rb_is_string(v)) != 0


def is_hash(v):
    return rffi.cast(lltype.Signed, rb_is_hash(v)) != 0


def is_nil(v):
    return rffi.cast(lltype.Signed, rb_is_nil(v)) != 0


def is_true(v):
    return rffi.cast(lltype.Signed, rb_is_true(v)) != 0


def is_false(v):
    return rffi.cast(lltype.Signed, rb_is_false(v)) != 0


def num2long(v):
    return rffi.cast(lltype.Signed, rb_num2long(v))


def ary_len(v):
    return rffi.cast(lltype.Signed, rb_ary_len(v))


def ary_entry(v, i):
    return rb_ary_entry(v, rffi.cast(rffi.LONG, i))


def hash_aref(hash_v, key):
    with rffi.scoped_str2charp(key) as c_key:
        return rb_hash_aref(hash_v, c_key)


def str_of(v):
    p = rb_cstr(v)
    if not p:
        raise RubyError('to_s')
    return rffi.charp2str(p)


def sym_of(v):
    p = rb_sym_cstr(v)
    if not p:
        raise RubyError('id2name')
    return rffi.charp2str(p)


def boot(argv):
    """Return (iseqw, status). iseqw is 0 when there is no ISeq to run."""
    # Never freed: ruby_sysinit stores this pointer in origarg (ruby.c)
    # and uses it for the process lifetime ($0, dladdr checks).
    c_argv = rffi.liststr2charpp(argv)
    with lltype.scoped_alloc(INTP.TO, 1) as status:
        status[0] = rffi.cast(rffi.INT, 0)
        n = rb_boot(rffi.cast(rffi.INT, len(argv)), c_argv, status)
        if not n:
            return rffi.cast(VALUE, 0), rffi.cast(lltype.Signed, status[0])
        return rb_iseqw_new(n), 0


def cleanup(status):
    return rffi.cast(lltype.Signed, rb_cleanup(rffi.cast(rffi.INT, status)))
