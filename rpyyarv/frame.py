import value
from rlib import hint


class Frame(object):
    # One frame per ISeq invocation: a call recurses into interp.execute()
    # with a fresh Frame, so Ruby call depth is interpreter recursion depth.
    _virtualizable_ = ['sp', 'stack[*]', 'locals[*]']

    def __init__(self, iseq, self_val, cref=0, entry=None):
        self = hint(self, access_directly=True, fresh_virtualizable=True)
        self.stack = [0] * iseq.stack_max
        self.sp = 0
        self.locals = [value.Q_NIL] * iseq.nlocals
        self.self_val = self_val
        # The class a class body defines into; 0 outside one, meaning Object.
        self.cref = cref
        # The MethodEntry being run, or None at toplevel and in a class body;
        # invokesuper needs the class the running method was defined on.
        self.entry = entry
        # The block this frame was called with, for invokeblock.
        self.block = None
        # For a block's frame, the block itself: throw needs it to name the
        # send a break unwinds to.
        self.own_block = None
        # For a block's frame, the frame it was written in: getlocal at a
        # non-zero level walks this chain, the way CRuby walks the EP chain.
        self.defining_frame = None
        # gcroots links live frames through this; not virtualizable.
        self.prev_frame = None

    def push(self, v):
        sp = self.sp
        assert sp >= 0
        self.stack[sp] = v
        self.sp = sp + 1

    def pop(self):
        sp = self.sp - 1
        assert sp >= 0
        v = self.stack[sp]
        # Cleared so the mark hook never revives a dead VALUE.
        self.stack[sp] = 0
        self.sp = sp
        return v
