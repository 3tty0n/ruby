import value
from rlib import hint

# frame.pending_kind: which throw a rescue/ensure ISeq is running under, so
# that its trailing `throw 0` can continue it (vm_insnhelper.c:1733).
PENDING_NONE = 0
PENDING_RAISE = 1
PENDING_BREAK = 2
PENDING_NEXT = 3


class Frame(object):
    # One frame per ISeq invocation: a call recurses into interp.execute()
    # with a fresh Frame, so Ruby call depth is interpreter recursion depth.
    _virtualizable_ = ['sp', 'pc', 'stack[*]', 'locals[*]']

    def __init__(self, iseq, self_val, cref=0, entry=None):
        self = hint(self, access_directly=True, fresh_virtualizable=True)
        self.stack = [0] * iseq.stack_max
        self.sp = 0
        # The pc of the instruction being run: an exception needs it to find
        # the catch-table entry covering it.
        self.pc = 0
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
        # The throw a rescue/ensure ISeq is unwinding; PENDING_NONE elsewhere.
        self.pending_kind = PENDING_NONE
        self.pending_value = 0
        self.pending_block = None

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

    def reset_sp(self, sp):
        """Back to the stack depth a catch-table entry names."""
        while self.sp > sp:
            self.pop()
        while self.sp < sp:
            self.push(value.Q_NIL)
