"""KIND_PROC/KIND_SYM hold a VALUE gcroots marks; KIND_ISEQ holds none."""

KIND_ISEQ = 0
KIND_PROC = 1
KIND_SYM = 2


class W_Block(object):
    _immutable_fields_ = ['kind', 'w_iseq', 'frame', 'outer', 'mid',
                          'is_lambda']

    def __init__(self, w_iseq, frame, outer, kind=KIND_ISEQ, proc_value=0,
                 mid=0, is_lambda=False):
        self.kind = kind
        self.w_iseq = w_iseq
        self.frame = frame
        # A `yield` inside a block reaches the enclosing method's block.
        self.outer = outer
        # KIND_PROC: the Proc; KIND_ISEQ: getblockparam's Proc, handle-owned.
        self.proc_value = proc_value
        self.mid = mid
        # A lambda checks arity and owns its `return` (VM_FRAME_FLAG_LAMBDA).
        self.is_lambda = is_lambda


def from_proc(v):
    return W_Block(None, None, None, KIND_PROC, v)


def from_symbol(mid):
    return W_Block(None, None, None, KIND_SYM, 0, mid)


class BlockNext(Exception):
    """A `next` the compiler could not turn into a jump."""
    def __init__(self, value):
        self.value = value


class BlockJump(Exception):
    """Unwind out of a block (vm_throw); not an error, so it may park."""
    def __init__(self, value):
        self.value = value


class BlockReturn(BlockJump):
    """`return`: tag is the defining method's frame (vm_insnhelper.c:1827)."""
    def __init__(self, frame, value):
        BlockJump.__init__(self, value)
        self.frame = frame


class BlockBreak(BlockJump):
    """`break`: the block is the tag, unwinding to the send that passed it."""
    def __init__(self, w_block, value):
        BlockJump.__init__(self, value)
        self.w_block = w_block


class BlockRetry(Exception):
    """A rescue body's `retry`, caught by the enclosing ISeq's retry entry."""
    pass
