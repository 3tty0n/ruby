"""RPython objects CRuby's stack scan misses, for the shim's mark hook."""

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import value
from rpyyarv.rlib import dont_look_inside, gc_mark_state


class Registry(object):
    def __init__(self):
        self.top = None         # innermost live Frame
        self.consts = []        # every loaded ISeq's constant pool
        self.pinned = []        # VALUEs built during load, before their pool
        self.classes = []       # classes RPyYARV defined, keys of the registry
        self.class_seen = {}    # the same, as a set: a root is never dropped
        self.held = []          # exception VALUEs parked outside any frame
        self.blocks = None      # interp's handle table, once it exists
        self.fibers = None      # fibers.mark_suspended, once installed
        # ponytail: leaks redefined blocks, bounded by define_method count.
        self.bmethods = []


state = Registry()


def register_blocks(blocks):
    """Handle-reachable blocks: nothing else keeps their locals marked."""
    state.blocks = blocks


def register_fibers(fn):
    """Passed as a function to keep this module below fibers.py."""
    state.fibers = fn


def register_bmethod(w_block):
    """A define_method body, kept alive for the life of the process."""
    state.bmethods.append(w_block)


def register_class(v):
    """Deduplicated: a cache fill asks per (klass, mid), not per class."""
    if value.is_immediate(v) or v in state.class_seen:
        return
    state.class_seen[v] = None
    state.classes.append(v)


def register_consts(consts):
    if len(consts) > 0:
        state.consts.append(consts)


def consts_mark():
    """Where a file's pools start, so a delegated file can drop its own."""
    return len(state.consts)


def consts_rollback(n):
    """A delegated file leaves no live ISeq: its pools are dead weight."""
    while len(state.consts) > n:
        state.consts.pop()


def keepalive(v):
    if not value.is_immediate(v):
        state.pinned.append(v)


def release_load_temporaries():
    state.pinned = []


def hold(v):
    """Keep a VALUE reachable while no frame covers it."""
    state.held.append(v)


def release(v):
    for i in range(len(state.held)):
        if state.held[i] == v:
            del state.held[i]
            return


def push_frame(frame):
    frame.prev_frame = state.top
    state.top = frame


def pop_frame(frame):
    state.top = frame.prev_frame
    frame.prev_frame = None


def _mark_array(a):
    i = 0
    n = len(a)
    while i < n:
        v = a[i]
        if not value.is_immediate(v):
            boot.gc_mark_value(v)
        i += 1


def _mark_frame(f):
    if f.marked_gen == gc_mark_state.generation:
        return
    f.marked_gen = gc_mark_state.generation
    _mark_frame_now(f)


def _mark_frame_now(f):
    _mark_array(f.slots)
    s = f.shared
    if s is not None:
        _mark_array(s.values)
    if not value.is_immediate(f.self_val):
        boot.gc_mark_value(f.self_val)
    # f.cref needs no mark: dispatch.root_base roots every Cref class.
    if not value.is_immediate(f.pending_value):
        boot.gc_mark_value(f.pending_value)
    _mark_block_procs(f.block)
    _mark_block_procs(f.own_block)
    _mark_block_procs(f.pending_block)


def _mark_block_procs(w_block):
    """Frames are marked elsewhere; only the Proc it carries is left."""
    while w_block is not None:
        if not value.is_immediate(w_block.proc_value):
            boot.gc_mark_value(w_block.proc_value)
        w_block = w_block.outer


def _mark_block_deep(w_block):
    """Undeduplicated: an incremental remark must see stores since pass 1."""
    while w_block is not None:
        if w_block.kind != block_mod.KIND_ISEQ \
                and not value.is_immediate(w_block.proc_value):
            boot.gc_mark_value(w_block.proc_value)
        f = w_block.frame
        while f is not None:
            _mark_frame_now(f)
            f = f.defining_frame
        w_block = w_block.outer


@dont_look_inside
def mark_handle(h):
    """One handle's env, alive exactly as long as its owner Proc."""
    b = state.blocks
    if b is None or h < 0 or h >= len(b.table):
        return
    w_block = b.table[h]
    if w_block is None:
        return
    prev = gc_mark_state.marking
    gc_mark_state.generation += 1
    gc_mark_state.marking = True
    try:
        v = b.selves[h]
        if not value.is_immediate(v):
            boot.gc_mark_value(v)
        _mark_block_deep(w_block)
    finally:
        gc_mark_state.marking = prev


def _mark_word(w):
    boot.gc_mark_maybe(w)


# Import time: force_now walks jitframe words (virtualizable.py, 0003).
gc_mark_state.mark_word = _mark_word


@dont_look_inside
def mark_roots():
    # Reading a frame mid-trace is not an escape; else every GC aborts it.
    # Restored, not cleared: a handle's dmark re-enters us from this walk.
    prev = gc_mark_state.marking
    gc_mark_state.generation += 1
    gc_mark_state.marking = True
    try:
        _mark_all()
    finally:
        gc_mark_state.marking = prev


def _mark_all():
    # Not _mark_array: resizable list, which the annotator keeps apart.
    pinned = state.pinned
    k = 0
    while k < len(pinned):
        v = pinned[k]
        if not value.is_immediate(v):
            boot.gc_mark_value(v)
        k += 1
    klasses = state.classes
    k = 0
    while k < len(klasses):
        boot.gc_mark_value(klasses[k])
        k += 1
    held = state.held
    k = 0
    while k < len(held):
        v = held[k]
        if not value.is_immediate(v):
            boot.gc_mark_value(v)
        k += 1
    pools = state.consts
    i = 0
    while i < len(pools):
        _mark_array(pools[i])
        i += 1
    bmethods = state.bmethods
    i = 0
    while i < len(bmethods):
        _mark_block_deep(bmethods[i])
        i += 1
    # Not the handle table: mark_handle does it, so dead Procs can die.
    # A compiled frame is not forced; mark_word walks its jitframe words.
    f = state.top
    while f is not None:
        _mark_frame(f)
        f = f.prev_frame
    # A suspended fiber's frames are on no chain of ours.
    if state.fibers is not None:
        state.fibers()


def root_census():
    """Sizes of every root set the mark hook walks, for the coverage report."""
    pools = 0
    i = 0
    while i < len(state.consts):
        pools += len(state.consts[i])
        i += 1
    return ('classes %d, const pools %d (%d values), pinned %d, held %d, '
            'bmethods %d' % (len(state.classes), len(state.consts), pools,
                             len(state.pinned), len(state.held),
                             len(state.bmethods)))


def install():
    # A plain function, so rffi adds the enter-RPython-from-C prologue.
    boot.set_mark_hook(mark_roots)
    boot.set_handle_mark(mark_handle)
