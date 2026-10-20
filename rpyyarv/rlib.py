import os

try:
    from rpython.rlib.jit import (
        JitDriver, elidable, promote, unroll_safe, dont_look_inside, hint)

    def oswrite(fd, s):
        os.write(fd, s)

    from rpython.rtyper.lltypesystem import lltype, rffi
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

except ImportError:
    class JitDriver(object):
        def __init__(self, **kwargs):
            pass

        def jit_merge_point(self, **kwargs):
            pass

        def can_enter_jit(self, **kwargs):
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
