"""CRuby's conservative stack scan misses frame stacks/locals and const pools since they're RPython objects; this keeps them enumerable for the shim's mark hook."""

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


state = Registry()


def register_blocks(blocks):
    """The blocks CRuby can reach through a handle; their defining frames may already have returned, so nothing else keeps their locals marked."""
    state.blocks = blocks


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
    """A block only the handle table holds: its defining frames may have returned, so their locals are reachable from nowhere else."""
    while w_block is not None:
        if not value.is_immediate(w_block.proc_value):
            boot.gc_mark_value(w_block.proc_value)
        f = w_block.frame
        while f is not None:
            _mark_frame(f)
            f = f.defining_frame
        w_block = w_block.outer


@dont_look_inside
def mark_roots():
    # Reading a frame mid-trace is correct and not an escape; without this flag every GC during a residual call aborted the trace being recorded.
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
    b = state.blocks
    if b is not None:
        table = b.table
        k = 0
        while k < len(table):
            _mark_block_deep(table[k])
            k += 1
        # The self each handed-over block was given, which nothing else roots.
        selves = b.selves
        k = 0
        while k < len(selves):
            v = selves[k]
            if not value.is_immediate(v):
                boot.gc_mark_value(v)
            k += 1
    # A frame in compiled code is still forced here (its VALUEs live in the jitframe); one mid-trace reads in place under the marking flag.
    f = state.top
    while f is not None:
        _mark_frame(f)
        f = f.prev_frame


def install():
    # A plain function, not an llhelper pointer, so rffi wraps it in the enter-RPython-from-C prologue. See boot.install_block_callback.
    boot.set_mark_hook(mark_roots)
