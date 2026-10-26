import os

try:
    from rpython.rlib.jit import (
        JitDriver, elidable, promote, unroll_safe, dont_look_inside, hint,
        set_user_param, TraceLimitTooHigh)
    from rpython.rlib.objectmodel import UnboxedValue, fetch_translated_config
    from rpython.rlib.rstackovf import StackOverflow, check_stack_overflow
    from rpython.rlib.rfloat import formatd

    def float_repr(x):
        return formatd(x, 'r', 0)

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

    def check_stack_overflow():
        pass

    def set_user_param(driver, text):
        pass

    def elidable(func):
        return func

    def promote(x):
        return x

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


def tagged_ints_enabled():
    config = fetch_translated_config()
    return config is not None and config.translation.taggedpointers
