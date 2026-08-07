import os

try:
    from rpython.rlib.jit import (
        JitDriver, elidable, promote, unroll_safe, dont_look_inside, hint)
    from rpython.rlib.objectmodel import always_inline
    from rpython.rlib.rarithmetic import LONG_BIT, ovfcheck
    from rpython.rtyper.lltypesystem import lltype, rffi

    _WORDP = rffi.CArrayPtr(rffi.LONG)
    _SHORTP = rffi.CArrayPtr(rffi.SHORT)

    def raw_word(addr, index):
        """The index'th machine word at a raw address, as a signed word."""
        return rffi.cast(lltype.Signed, rffi.cast(_WORDP, addr)[index])

    def raw_short(addr, index):
        """The index'th C short at a raw address, as a signed word."""
        return rffi.cast(lltype.Signed, rffi.cast(_SHORTP, addr)[index])

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

    def always_inline(func):
        return func

    def raw_word(addr, index):
        raise NotImplementedError('raw_word needs the RPython backend')

    def raw_short(addr, index):
        raise NotImplementedError('raw_short needs the RPython backend')

    def oswrite(fd, s):
        if not isinstance(s, bytes):
            s = s.encode('utf-8')
        os.write(fd, s)
