"""A block: an ISeq plus the frame it was written in.

No VALUE is stored here; self comes from the defining frame, which the mark
hook already walks and which stays on gcroots' registry even while the block
is suspended inside rb_block_call.
"""


class W_Block(object):
    _immutable_fields_ = ['w_iseq', 'frame', 'outer']

    def __init__(self, w_iseq, frame, outer):
        self.w_iseq = w_iseq
        self.frame = frame
        # A `yield` inside a block reaches the enclosing method's block.
        self.outer = outer


class BlockNext(Exception):
    """A `next` the compiler could not turn into a jump."""
    def __init__(self, value):
        self.value = value


class BlockBreak(Exception):
    """`break`: the block itself is the tag, so it unwinds to the send that
    passed this exact one."""
    def __init__(self, w_block, value):
        self.w_block = w_block
        self.value = value
