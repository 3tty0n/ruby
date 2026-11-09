import os

try:
    from rpython.rlib.jit import (
        JitDriver, elidable, promote, unroll_safe, dont_look_inside, hint,
        set_user_param, TraceLimitTooHigh)
    from rpython.rlib.objectmodel import (
        UnboxedValue, compute_hash, compute_identity_hash, compute_unique_id,
        fetch_translated_config, r_dict, we_are_translated)
    from rpython.rlib.rstackovf import StackOverflow, check_stack_overflow
    from rpython.rlib.rfloat import formatd
    from rpython.rlib.rarithmetic import ovfcheck
    from rpython.rlib.rbigint import rbigint

    def float_repr(x):
        return formatd(x, 'r', 0)

    def float_fixed(x, precision):
        if not we_are_translated():
            return _float_fixed_ctypes(x, precision)
        from rpyyarv import boot
        return boot.format_fixed(x, precision)

    def oswrite(fd, s):
        os.write(fd, s)

    from rpython.rtyper.lltypesystem import lltype, rffi
    from rpython.rlib.rarithmetic import LONG_BIT
    from rpython.translator.tool.cbuild import ExternalCompilationInfo

    # TODO: extract the following definition to a different file to keep this
    # rlib as an interface to the RPyton library (rlib)
    _now_eci = ExternalCompilationInfo(
        includes=['time.h'],
        post_include_bits=['RPY_EXTERN long long rpyyarv_now_ns(void);'],
        separate_module_sources=['''
#include <time.h>
RPY_EXTERN long long rpyyarv_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}
'''])
    _c_now_ns = rffi.llexternal('rpyyarv_now_ns', [], rffi.LONGLONG,
                                compilation_info=_now_eci,
                                releasegil=False, _nowrapper=True)

    # TODO: same to the above
    def now_ns():
        return rffi.cast(lltype.Signed, _c_now_ns())

    assert LONG_BIT == 64, 'now_ns() needs a 64-bit Signed to hold nanoseconds'

except ImportError:
    def fetch_translated_config():
        return None

    class UnboxedValue(object):
        def __init__(self, value):
            import sys
            limit = sys.maxsize >> 1
            if value < -limit - 1 or value > limit:
                raise OverflowError('UnboxedValue: argument out of range')
            self.intval = value

    class JitDriver(object):
        def __init__(self, **kwargs):
            pass

        def jit_merge_point(self, **kwargs):
            pass

        def can_enter_jit(self, **kwargs):
            pass

    class TraceLimitTooHigh(Exception):
        pass

    StackOverflow = RuntimeError

    float_repr = repr

    def float_fixed(x, precision):
        return _float_fixed_ctypes(x, precision)

    def ovfcheck(r):
        import sys
        if not -sys.maxsize - 1 <= r <= sys.maxsize:
            raise OverflowError
        return r

    class rbigint(object):
        # The part of rpython.rlib.rbigint's interface RPyYARV uses
        def __init__(self, value):
            self.value = value

        @staticmethod
        def fromint(value):
            return rbigint(value)

        @staticmethod
        def fromfloat(value):
            return rbigint(int(value))

        def toint(self):
            return ovfcheck(self.value)

        def tofloat(self):
            return float(self.value)

        def str(self):
            return str(self.value)

        def bit_length(self):
            return self.value.bit_length()

        def add(self, other):
            return rbigint(self.value + other.value)

        def sub(self, other):
            return rbigint(self.value - other.value)

        def mul(self, other):
            return rbigint(self.value * other.value)

        def floordiv(self, other):
            return rbigint(self.value // other.value)

        def mod(self, other):
            return rbigint(self.value % other.value)

        def pow(self, other):
            return rbigint(self.value ** other.value)

        def neg(self):
            return rbigint(-self.value)

        def eq(self, other):
            return self.value == other.value

        def lt(self, other):
            return self.value < other.value

        def le(self, other):
            return self.value <= other.value

        def gt(self, other):
            return self.value > other.value

        def ge(self, other):
            return self.value >= other.value

    def check_stack_overflow():
        pass

    def set_user_param(driver, text):
        pass

    def elidable(func):
        return func

    def promote(x):
        return x

    def compute_unique_id(x):
        return id(x)

    compute_hash = hash
    compute_identity_hash = id

    class _DictKey(object):
        def __init__(self, d, key):
            self.d = d
            self.key = key

        def __eq__(self, other):
            return self.d.key_eq(self.key, other.key)

        def __hash__(self):
            return self.d.key_hash(self.key)

    class r_dict(object):
        def __init__(self, key_eq, key_hash):
            self.key_eq = key_eq
            self.key_hash = key_hash
            self.entries = {}

        def get(self, key, default):
            return self.entries.get(_DictKey(self, key), default)

        def __setitem__(self, key, value):
            self.entries[_DictKey(self, key)] = value

    def unroll_safe(func):
        return func

    def dont_look_inside(func):
        return func

    def hint(x, **kwds):
        return x

    def oswrite(fd, s):
        if not isinstance(s, bytes):
            s = s.encode('utf-8')
        os.write(fd, s)

    import time

    def now_ns():
        return time.monotonic_ns()


# Untranslated, the shim is reached through ctypes: rffi would recompile it
def _float_fixed_ctypes(x, precision):
    import ctypes
    here = os.path.dirname(os.path.abspath(__file__))
    for ext in ('dylib', 'so'):
        path = os.path.join(here, 'librpyyarv_boot.' + ext)
        if os.path.exists(path):
            fn = ctypes.CDLL(path).rpyyarv_format_fixed
            break
    fn.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int,
                   ctypes.c_double]
    n = fn(None, 0, precision, x)
    buf = ctypes.create_string_buffer(n + 1)
    fn(buf, n + 1, precision, x)
    return str(buf.value.decode('ascii'))


def tagged_ints_enabled():
    config = fetch_translated_config()
    return config is not None and config.translation.taggedpointers
