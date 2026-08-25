import os

try:
    from rpython.rlib.jit import (
        JitDriver, elidable, promote, unroll_safe, dont_look_inside, hint,
        set_user_param, gc_mark_state, we_are_jitted)
    from rpython.rlib.objectmodel import always_inline
    from rpython.rlib.longlong2float import float2longlong, longlong2float
    from rpython.rlib.rarithmetic import LONG_BIT, intmask, ovfcheck, r_uint
    from rpython.rlib.rfloat import INFINITY, NAN
    from rpython.rlib.rstackovf import StackOverflow, check_stack_overflow
    from rpython.rlib import rstack
    from rpython.rtyper.lltypesystem import lltype, rffi

    def set_stack_length(nbytes):
        """Raise the soft stack limit; stack.c clamps it to 3/4 RLIMIT_STACK."""
        cur = rstack._stack_get_length()
        if cur > 0 and nbytes > cur:
            rstack._stack_set_length_fraction(float(nbytes) / float(cur))
        return rstack._stack_get_length()

    from rpython.rtyper.lltypesystem.lloperation import llop

    def on_foreign_stack():
        """True on a foreign stack; the depth check would read overflow."""
        current = llop.stack_current(lltype.Signed)
        return r_uint(rstack._stack_get_end() - current) \
            > r_uint(rstack._stack_get_length())

    def unchecked_stack_start():
        rstack._stack_criticalcode_start()

    def unchecked_stack_stop():
        rstack._stack_criticalcode_stop()

    _WORDP = rffi.CArrayPtr(rffi.LONG)
    _SHORTP = rffi.CArrayPtr(rffi.SHORT)

    def raw_word(addr, index):
        return rffi.cast(lltype.Signed, rffi.cast(_WORDP, addr)[index])

    def set_raw_word(addr, index, v):
        rffi.cast(_WORDP, addr)[index] = rffi.cast(rffi.LONG, v)

    def raw_short(addr, index):
        return rffi.cast(lltype.Signed, rffi.cast(_SHORTP, addr)[index])

    def bits2float(w):
        """Word w as a double: a JIT-visible reinterpret, not a call."""
        return longlong2float(rffi.cast(rffi.LONGLONG, w))

    def float2bits(f):
        return rffi.cast(lltype.Signed, float2longlong(f))

    def oswrite(fd, s):
        os.write(fd, s)

    from rpython.rlib import rgc
    from rpython.rlib.rtime import time as _clock

    # rtime.time() raw-mallocs on purpose, so the mark hook may call it.
    def clock_ns():
        return int(_clock() * 1000000000.0)

    def rpython_heap_bytes():
        return rgc.get_stats(rgc.TOTAL_MEMORY)

except ImportError:
    import struct
    import sys
    LONG_BIT = 64 if sys.maxsize > 2 ** 32 else 32
    INFINITY = float('inf')
    NAN = float('nan')

    def ovfcheck(x):
        return x

    def r_uint(x):
        return x & ((1 << LONG_BIT) - 1)

    def intmask(x):
        x &= (1 << LONG_BIT) - 1
        if x >= 1 << (LONG_BIT - 1):
            x -= 1 << LONG_BIT
        return x

    def bits2float(w):
        return struct.unpack('<d', struct.pack('<q', intmask(w)))[0]

    def float2bits(f):
        return struct.unpack('<q', struct.pack('<d', f))[0]

    StackOverflow = RuntimeError

    def check_stack_overflow():
        pass

    def on_foreign_stack():
        return False

    def unchecked_stack_start():
        pass

    def unchecked_stack_stop():
        pass

    def set_stack_length(nbytes):
        return 0

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

    def we_are_jitted():
        return False

    def hint(x, **kwds):
        return x

    def set_user_param(driver, text):
        pass

    import time as _time

    def clock_ns():
        return int(_time.time() * 1000000000.0)

    def rpython_heap_bytes():
        return 0

    def always_inline(func):
        return func

    class _GCMarkState(object):
        def __init__(self):
            self.marking = False
            self.generation = 0
            self.mark_word = None

    gc_mark_state = _GCMarkState()

    def raw_word(addr, index):
        raise NotImplementedError('raw_word needs the RPython backend')

    def set_raw_word(addr, index, v):
        raise NotImplementedError('set_raw_word needs the RPython backend')

    def raw_short(addr, index):
        raise NotImplementedError('raw_short needs the RPython backend')

    def oswrite(fd, s):
        if not isinstance(s, bytes):
            s = s.encode('utf-8')
        os.write(fd, s)
