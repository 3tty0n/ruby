"""FFI setup, VALUE types, and shim call plumbing (boot_shim.c)."""
from __future__ import absolute_import
import os
import sys

from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.rlib.rthread import ThreadLocalReference
from rpython.translator.tool.cbuild import ExternalCompilationInfo

from rpyyarv import symbols
from rpyyarv.error import RubyException


_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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



# The arch name, not a path: fixed by the libruby this binary links against.
_ARCH = os.path.basename(_arch_include_dir())


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


THREAD_HOOK = lltype.Ptr(lltype.FuncType([], lltype.Void))


CONST_HOOK = lltype.Ptr(lltype.FuncType([], lltype.Void))

METHOD_HOOK = lltype.Ptr(lltype.FuncType([VALUE, VALUE], lltype.Void))


BLOCK_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed, rffi.INT, VALUEP,
                                         VALUE, VALUE, VALUE], VALUE))


# (self, mid, argc, argv, blockproc, kw, status, errval) -> result
TRAMP_HOOK = lltype.Ptr(lltype.FuncType(
    [VALUE, VALUE, VALUE, VALUE, rffi.INT, VALUEP, VALUE, rffi.INT, INTP,
     VALUEP], VALUE))


# Mirrors RPYYARV_MAX_ARGC; a splat can expand past 32 (fileutils passes 47).
MAX_ARGC = 256


def _ext(name, args, result, reenters=False, marks=False, releasegil=False):
    # Most shim calls keep GIL to preserve CRuby/RPython lock ordering.
    return rffi.llexternal(name, args, result, compilation_info=eci,
                           releasegil=releasegil,
                           random_effects_on_gcobjs=reenters,
                           forces_virtualizable=marks)


HANDLE_MARK_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed], lltype.Void))


FIBER_SAVE_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed], VOIDP))
FIBER_ARRIVE_HOOK = lltype.Ptr(lltype.FuncType(
    [lltype.Signed, lltype.Signed, lltype.Signed], VOIDP))


FIBER_BORN_HOOK = lltype.Ptr(lltype.FuncType(
    [lltype.Signed, lltype.Signed, lltype.Signed], lltype.Void))


FIBER_KEY_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed], lltype.Void))


rb_take_errinfo = _ext('rpyyarv_take_errinfo', [], VALUE)


def _v(n):
    return rffi.cast(VALUE, n)


# One cell per shim nesting level; CRuby can trampoline back in, so they nest.
SHIM_DEPTH = 64


class _Nesting(object):
    def __init__(self):
        self.status = 0
        self.argv = 0
        self.foreign = 0
        self.status_pool = lltype.malloc(INTP.TO, SHIM_DEPTH, flavor='raw',
                                         zero=True)
        self.argv_pool = lltype.malloc(
            rffi.CArray(VALUE), SHIM_DEPTH * (MAX_ARGC + 1),
            flavor='raw', zero=True)


_nesting = _Nesting()
_nesting_tls = ThreadLocalReference(_Nesting)


def init_thread_state():
    if _nesting_tls.get() is None:
        _nesting_tls.set(_nesting)


def release_thread_state():
    nesting = _nesting_tls.get()
    if nesting is None or nesting is _nesting:
        return
    assert (nesting.status == 0 and nesting.argv == 0
            and nesting.foreign == 0)
    lltype.free(nesting.status_pool, flavor='raw')
    lltype.free(nesting.argv_pool, flavor='raw')
    _nesting_tls.set(None)


def _current_nesting():
    nesting = _nesting_tls.get()
    if nesting is None:
        nesting = _Nesting()
        _nesting_tls.set(nesting)
    return nesting


def nesting_depth():
    """Protected calls in flight; equal depth means the same CRuby frame."""
    return _current_nesting().status


def set_nesting_depths(status, argv):
    nesting = _current_nesting()
    nesting.status = status
    nesting.argv = argv


def nesting_depths():
    nesting = _current_nesting()
    return nesting.status, nesting.argv


def foreign_depth():
    return _current_nesting().foreign


def set_foreign_depth(depth):
    _current_nesting().foreign = depth


def enter_foreign_depth():
    nesting = _current_nesting()
    nesting.foreign += 1


def leave_foreign_depth():
    nesting = _current_nesting()
    nesting.foreign -= 1
    return nesting.foreign


def _enter_status():
    """Status cell for one shim call; past SHIM_DEPTH, a fresh raw cell."""
    nesting = _current_nesting()
    d = nesting.status
    nesting.status = d + 1
    if d >= SHIM_DEPTH:
        p = lltype.malloc(INTP.TO, 1, flavor='raw')
    else:
        p = rffi.ptradd(nesting.status_pool, d)
    p[0] = rffi.cast(rffi.INT, 0)
    return p


FOREIGN_TAG = -2


class ForeignJump(Exception):
    """A tag CRuby aimed past our frames; boot_shim re-issues it."""


def _leave_status_code(p):
    nesting = _current_nesting()
    d = nesting.status - 1
    nesting.status = d
    code = rffi.cast(lltype.Signed, p[0])
    if d >= SHIM_DEPTH:
        lltype.free(p, flavor='raw')
    return code


def _leave_status(p):
    nesting = _current_nesting()
    d = nesting.status - 1
    nesting.status = d
    failed = rffi.cast(lltype.Signed, p[0]) != 0
    if d >= SHIM_DEPTH:
        lltype.free(p, flavor='raw')
    return failed


def _enter_argv(n):
    """Copied to the machine stack before anything allocates, so unscanned."""
    assert n <= MAX_ARGC
    nesting = _current_nesting()
    d = nesting.argv
    nesting.argv = d + 1
    if d >= SHIM_DEPTH:
        return lltype.malloc(rffi.CArray(VALUE), n + 1, flavor='raw')
    return rffi.ptradd(nesting.argv_pool, d * (MAX_ARGC + 1))


def _leave_argv(p):
    nesting = _current_nesting()
    d = nesting.argv - 1
    nesting.argv = d
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
    """Off the send path, where resolving the name costs a dict lookup."""
    _failed(symbols.name_of(mid))
