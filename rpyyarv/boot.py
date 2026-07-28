"""CRuby boot and ISeq handoff
"""

import os

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


eci = ExternalCompilationInfo(
    includes=['ruby.h', 'boot_shim.h'],
    include_dirs=[os.path.join(_TOP, 'include'), _arch_include_dir(), _HERE],
    separate_module_files=[os.path.join(_HERE, 'boot_shim.c')],
    libraries=[_libruby_name()],
    library_dirs=[_BUILD],
    link_extra=['-Wl,-rpath,' + _BUILD],
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
