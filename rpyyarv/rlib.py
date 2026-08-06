import os

try:
    from rpython.rlib.jit import (
        JitDriver, elidable, promote, unroll_safe, dont_look_inside, hint)
    from rpython.rlib.rarithmetic import LONG_BIT, ovfcheck

    def oswrite(fd, s):
        os.write(fd, s)

except ImportError:
    import sys
    LONG_BIT = 64 if sys.maxsize > 2 ** 32 else 32

    def ovfcheck(x):
        return x

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
