"""A block: an ISeq plus the frame it was written in.

No VALUE is stored here. self is read from the defining frame, whose stack
and locals the mark hook already walks, so a block adds nothing new for the
GC to reach -- including while it is suspended inside rb_block_call, since
the defining frame is still on gcroots' registry then.
"""


class W_Block(object):
    _immutable_fields_ = ['w_iseq', 'frame', 'outer']

    def __init__(self, w_iseq, frame, outer):
        self.w_iseq = w_iseq
        self.frame = frame
        # The block the defining frame itself was called with: a `yield`
        # inside a block reaches the enclosing method's block, not this one.
        self.outer = outer


class BlockNext(Exception):
    """`next value` from somewhere the compiler could not turn into a jump:
    the block returns the value."""
    def __init__(self, value):
        self.value = value


class BlockBreak(Exception):
    """`break value`: unwinds to the send that passed this exact block, which
    is why the block itself is the tag. Nested blocks each match their own."""
    def __init__(self, w_block, value):
        self.w_block = w_block
        self.value = value
