"""A fiber suspends without unwinding, so every process-global stack RPyYARV keeps outside the machine stack is saved and restored around each switch, keyed by rb_fiber_t*."""

from rpython.rlib import rgc
from rpython.rlib import rstack
from rpython.rlib._stacklet_shadowstack import (STACKLET, alloc_stacklet,
                                                lambda_customtrace)
from rpython.rtyper.lltypesystem import llmemory, lltype, rffi
from rpython.rtyper.lltypesystem.lloperation import llop

from rpyyarv import boot
from rpyyarv import gcroots
from rpyyarv import interp
from rpyyarv import requires
from rpyyarv import rubycall
from rpyyarv.rlib import (raw_word, set_raw_word, unchecked_stack_start,
                          unchecked_stack_stop)

SIZEADDR = llmemory.sizeof(llmemory.Address)


class _Anchors(object):
    """RPython's stack-depth window (rpy_stacktoobig end/length). Left on the main stack, a coroutine stack reads as permanently full: tracing, bridges and even entry into compiled loops are then silently refused, so the JIT dies inside every fiber."""

    def __init__(self):
        self.end_adr = 0
        self.length_adr = 0
        self.main_end = 0
        self.main_length = 0


anchors = _Anchors()


def _anchor_stack(base, size):
    """Point the depth window at the stack now running; base 0 is the root fiber, whose window was captured at install."""
    if anchors.end_adr == 0:
        return
    if base == 0:
        set_raw_word(anchors.end_adr, 0, anchors.main_end)
        set_raw_word(anchors.length_adr, 0, anchors.main_length)
    else:
        set_raw_word(anchors.end_adr, 0, base + size)
        set_raw_word(anchors.length_adr, 0, size - (size >> 2))


class FiberState(object):
    """One fiber's half of the globals. ss.s_sscopy holds its shadowstack copy while it is suspended, which the GC walks through STACKLET's custom trace hook."""

    def __init__(self):
        self.ss = alloc_stacklet()
        self.cap = 0                # bytes s_sscopy can hold, minus the header
        self.dead = False
        self.top = None             # gcroots' innermost frame
        # The pooled shim cells are indexed by a global counter, which a fiber
        # suspended inside a boundary call would leave behind; past SHIM_DEPTH
        # every cell is freshly malloced instead.
        # ponytail: a fiber pays a raw_malloc per boundary call. Give FiberState its own pool if a fiber-heavy workload measures it.
        self.status_depth = boot.SHIM_DEPTH
        self.argv_depth = boot.SHIM_DEPTH
        self.foreign_depth = 0
        self.files = []
        self.relative = ''


class _Registry(object):
    def __init__(self):
        self.states = {}        # rb_fiber_t* -> FiberState
        self.live = []          # the same states, walkable without allocating
        self.dead = 0


registry = _Registry()


def _reap():
    """Entries fiber_free could only flag, since it runs inside CRuby's sweep."""
    if registry.dead == 0:
        return
    registry.dead = 0
    live = []
    for st in registry.live:
        if not st.dead:
            live.append(st)
    registry.live = live
    for key in registry.states.keys():
        if registry.states[key].dead:
            del registry.states[key]


def _state_for(key):
    if key in registry.states:
        st = registry.states[key]
        if not st.dead:
            return st
        # CRuby handed the same address to a new fiber; drop the old entry first.
        _reap()
    st = FiberState()
    registry.states[key] = st
    registry.live.append(st)
    return st


def _save(st):
    st.top = gcroots.state.top
    st.status_depth = boot._nesting.status
    st.argv_depth = boot._nesting.argv
    st.foreign_depth = interp.foreign_stack.depth
    st.files = requires.files.stack
    st.relative = rubycall.relative.path


def _restore(st):
    gcroots.state.top = st.top
    st.top = None
    boot._nesting.status = st.status_depth
    boot._nesting.argv = st.argv_depth
    interp.foreign_stack.depth = st.foreign_depth
    requires.files.stack = st.files
    rubycall.relative.path = st.relative
    # The stack-depth check is one process-wide flag, so it follows whichever fiber is running.
    if st.foreign_depth > 0:
        unchecked_stack_start()
    else:
        unchecked_stack_stop()


def park(key):
    """The buffer the shim copies this fiber's shadowstack into. Nothing here may allocate once the buffer is attached: its length still reads 0, so a collection would walk none of the roots it is about to hold."""
    st = _state_for(key)
    _save(st)
    top = llop.gc_adr_of_root_stack_top(llmemory.Address).address[0]
    base = llop.gc_adr_of_root_stack_base(llmemory.Address).address[0]
    # Measured with this call's own frame on the stack, so never smaller than what the shim copies once it returns.
    length = top - base
    buf = st.ss.s_sscopy
    if length > st.cap or not buf:
        st.ss.s_sscopy = llmemory.NULL
        if buf:
            llmemory.raw_free(buf)
        st.cap = 0
        buf = llmemory.raw_malloc(SIZEADDR + length)
        if not buf:
            return lltype.nullptr(rffi.VOIDP.TO)
        st.cap = length
    buf.signed[0] = 0
    st.ss.s_sscopy = buf
    llop.gc_writebarrier(lltype.Void, llmemory.cast_ptr_to_adr(st.ss))
    llop.gc_modified_shadowstack(lltype.Void)
    return rffi.cast(rffi.VOIDP, buf)


def unpark(key, stack_base, stack_size):
    """The buffer the shim copies back; it stays attached, with its length zeroed, so the next park can reuse it."""
    _anchor_stack(stack_base, stack_size)
    if key not in registry.states:
        return lltype.nullptr(rffi.VOIDP.TO)
    st = registry.states[key]
    _restore(st)
    llop.gc_modified_shadowstack(lltype.Void)
    return rffi.cast(rffi.VOIDP, st.ss.s_sscopy)


def born(key, stack_base, stack_size):
    """A fiber running its first instruction: the resuming fiber left the shadowstack empty, and none of the globals belong to this one."""
    _anchor_stack(stack_base, stack_size)
    _reap()
    st = _state_for(key)
    st.top = None
    st.status_depth = boot.SHIM_DEPTH
    st.argv_depth = boot.SHIM_DEPTH
    st.foreign_depth = 0
    st.files = []
    st.relative = ''
    _restore(st)
    llop.gc_modified_shadowstack(lltype.Void)


def died(key):
    """From fiber_free, so a fiber the GC reaped mid-flight passes here too. Called during CRuby's sweep: flag it and let the next born reclaim it."""
    if key not in registry.states:
        return
    st = registry.states[key]
    if st.dead:
        return
    st.dead = True
    st.top = None
    registry.dead += 1


def mark_suspended():
    """Every suspended fiber's frames, from the shim's mark hook; CRuby marks their machine stacks conservatively for as long, so this adds no lifetime."""
    live = registry.live
    i = 0
    while i < len(live):
        st = live[i]
        f = st.top
        while f is not None:
            gcroots._mark_frame(f)
            f = f.prev_frame
        i += 1


def install():
    rgc.register_custom_trace_hook(STACKLET, lambda_customtrace)
    gcroots.register_fibers(mark_suspended)
    # Capture the main stack's depth window as _raise_stack_limit left it (touching the length here would undo the 4MB deep-recursion limit); the slowpath only anchors the lazy end without changing it.
    anchors.end_adr = rstack._stack_get_end_adr()
    anchors.length_adr = rstack._stack_get_length_adr()
    if raw_word(anchors.end_adr, 0) == 0:
        rstack._stack_too_big_slowpath(llop.stack_current(lltype.Signed))
    anchors.main_end = raw_word(anchors.end_adr, 0)
    anchors.main_length = raw_word(anchors.length_adr, 0)
    base_slot = rffi.cast(rffi.VOIDP,
                          llop.gc_adr_of_root_stack_base(llmemory.Address))
    top_slot = rffi.cast(rffi.VOIDP,
                         llop.gc_adr_of_root_stack_top(llmemory.Address))
    # Plain functions, not llhelper pointers: only then does rffi build the enter-RPython-from-C wrappers. See boot.install_block_callback.
    boot.set_fiber_hooks(park, unpark, born, died, base_slot, top_slot)
