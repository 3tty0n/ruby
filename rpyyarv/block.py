"""KIND_ISEQ carries no VALUE (self comes from the defining frame, walked by the mark hook); KIND_PROC/KIND_SYM hold a VALUE, so gcroots marks them too."""

KIND_ISEQ = 0
KIND_PROC = 1
KIND_SYM = 2


class W_Block(object):
    _immutable_fields_ = ['kind', 'w_iseq', 'frame', 'outer', 'mid']

    def __init__(self, w_iseq, frame, outer, kind=KIND_ISEQ, proc_value=0,
                 mid=0):
        self.kind = kind
        self.w_iseq = w_iseq
        self.frame = frame
        # A `yield` inside a block reaches the enclosing method's block.
        self.outer = outer
        # KIND_PROC: the Proc itself. KIND_ISEQ: the Proc getblockparam materialises for it, once one exists; the handle table owns it.
        self.proc_value = proc_value
        self.mid = mid


def from_proc(v):
    return W_Block(None, None, None, KIND_PROC, v)


def from_symbol(mid):
    return W_Block(None, None, None, KIND_SYM, 0, mid)


class BlockNext(Exception):
    """A `next` the compiler could not turn into a jump."""
    def __init__(self, value):
        self.value = value


class BlockJump(Exception):
    """An unwind out of a block, as vm_throw starts one; not an error, so it may park and be re-raised."""
    def __init__(self, value):
        self.value = value


class BlockReturn(BlockJump):
    """A non-local `return`: the tag is the frame of the block's defining method, found as its local EP (vm_throw_start, vm_insnhelper.c:1827)."""
    def __init__(self, frame, value):
        BlockJump.__init__(self, value)
        self.frame = frame


class BlockBreak(BlockJump):
    """`break`: the block itself is the tag, so it unwinds to the send that passed this exact one."""
    def __init__(self, w_block, value):
        BlockJump.__init__(self, value)
        self.w_block = w_block
