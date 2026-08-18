"""CRuby's conservative stack scan misses frame stacks/locals and const pools since they're RPython objects; this keeps them enumerable for the shim's mark hook."""

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
        self.held = []          # exception VALUEs parked outside any frame
        self.blocks = None      # interp's handle table, once it exists
        self.fibers = None      # fibers.mark_suspended, once fibers are installed
        # ponytail: grows monotonically, a redefined name leaks its old block until process end -- bounded by define_method call count.
        self.bmethods = []


state = Registry()


def register_blocks(blocks):
    """The blocks CRuby can reach through a handle; their defining frames may already have returned, so nothing else keeps their locals marked."""
    state.blocks = blocks


def register_fibers(fn):
    """fibers.mark_suspended, passed as a function so this module keeps its place below fibers.py."""
    state.fibers = fn


def register_bmethod(w_block):
    """A define_method body dispatch.define_bmethod now runs directly, kept alive for the life of the process."""
    state.bmethods.append(w_block)


def register_class(v):
    if not value.is_immediate(v):
        state.classes.append(v)


def register_consts(consts):
    if len(consts) > 0:
        state.consts.append(consts)


def keepalive(v):
    if not value.is_immediate(v):
        state.pinned.append(v)


def release_load_temporaries():
    state.pinned = []


def hold(v):
    """Keep a VALUE reachable while it waits in an RPython field no frame covers."""
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
    _mark_array(f.stack)
    _mark_array(f.locals)
    s = f.shared
    if s is not None:
        _mark_array(s.values)
    if not value.is_immediate(f.self_val):
        boot.gc_mark_value(f.self_val)
    # f.cref needs no mark: every class a Cref names went through dispatch.root_base, which roots it for good.
    if not value.is_immediate(f.pending_value):
        boot.gc_mark_value(f.pending_value)
    _mark_block_procs(f.block)
    _mark_block_procs(f.own_block)
    _mark_block_procs(f.pending_block)


def _mark_block_procs(w_block):
    """A block whose frames something else already marks: only the Proc it may carry is left."""
    while w_block is not None:
        if not value.is_immediate(w_block.proc_value):
            boot.gc_mark_value(w_block.proc_value)
        w_block = w_block.outer


def _mark_block_deep(w_block):
    """An escaped block's env, from its owner Proc's dmark: its defining frames may have returned, so nothing else roots their locals. Undeduplicated, since an incremental remark must see stores made since the first pass; the ISEQ block's own Proc is the caller being marked."""
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
    """One handle's env, called from its owner Proc's dmark: alive exactly as long as the Proc, so a clique of Procs and Scopes nobody holds dies whole."""
    b = state.blocks
    if b is None or h < 0 or h >= len(b.table):
        return
    w_block = b.table[h]
    if w_block is None:
        return
    gc_mark_state.generation += 1
    gc_mark_state.marking = True
    try:
        v = b.selves[h]
        if not value.is_immediate(v):
            boot.gc_mark_value(v)
        _mark_block_deep(w_block)
    finally:
        gc_mark_state.marking = False


def _mark_word(w):
    boot.gc_mark_maybe(w)


# Installed at import time so force_now can walk a compiled frame's jitframe
# words instead of deoptimizing it (metainterp/virtualizable.py, patch 0003).
gc_mark_state.mark_word = _mark_word


@dont_look_inside
def mark_roots():
    # Reading a frame mid-trace is correct and not an escape; without this flag every GC during a residual call aborted the trace being recorded.
    gc_mark_state.generation += 1
    gc_mark_state.marking = True
    try:
        _mark_all()
    finally:
        gc_mark_state.marking = False


def _mark_all():
    # Not _mark_array: this list is resized, the pools are not, and the annotator will not merge the two list kinds.
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
    # The handle table is not walked here: each handle's env is marked from its owner Proc's dmark (mark_handle), so unreferenced Procs can die.
    # A frame in compiled code is not forced: its stale heap arrays are read (harmless extra marks) and its live jitframe words are walked once via mark_word.
    f = state.top
    while f is not None:
        _mark_frame(f)
        f = f.prev_frame
    # A suspended fiber's frames are on no chain of ours; its own saved one still holds them.
    if state.fibers is not None:
        state.fibers()


def install():
    # A plain function, not an llhelper pointer, so rffi wraps it in the enter-RPython-from-C prologue. See boot.install_block_callback.
    boot.set_mark_hook(mark_roots)
    boot.set_handle_mark(mark_handle)
