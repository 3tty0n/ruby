from rpyyarv import value
from rpyyarv.rlib import hint

# Which throw a rescue/ensure ISeq runs under, so its trailing `throw 0` can continue it (vm_insnhelper.c:1733).
PENDING_NONE = 0
PENDING_RAISE = 1
PENDING_BREAK = 2
PENDING_NEXT = 3
PENDING_RETURN = 4


class Frame(object):
    # One per ISeq invocation, so Ruby call depth is RPython recursion depth.
    _virtualizable_ = ['sp', 'pc', 'stack[*]', 'locals[*]']

    # VM_FRAME_FLAG_MODIFIED_BLOCK_PARAM (insns.def:111); left to the rtyper's zero-init so the common no-block-param call pays no store.
    block_param_set = False

    # A module body that ran `module_function` with no arguments; every def after it becomes private plus a singleton method (vm_method.c rb_mod_modfunc).
    module_func = False

    # Set on the way out of execute(); a `return` whose target frame is already gone is the orphaned Proc vm_throw_start answers with a LocalJumpError.
    dead = False

    def __init__(self, iseq, self_val, cref=None, entry=None):
        self = hint(self, access_directly=True, fresh_virtualizable=True)
        self.w_iseq = iseq
        self.stack = [0] * iseq.stack_max
        self.sp = 0
        # The pc of the running instruction, for finding a catch-table entry.
        self.pc = 0
        self.locals = [value.Q_NIL] * iseq.nlocals
        self.self_val = self_val
        # The interp.Cref a class body pushed, None outside one; its klass is what a def in the body lands on.
        self.cref = cref
        # The running MethodEntry, which invokesuper resumes above.
        self.entry = entry
        self.block = None
        # For a block's frame, the block itself: a break's unwind tag.
        self.own_block = None
        # For a block's frame, the frame it was written in; getlocal at a non-zero level walks this chain, as CRuby walks the EP chain.
        self.defining_frame = None
        # gcroots links live frames through this; not virtualizable.
        self.prev_frame = None
        self.pending_kind = PENDING_NONE
        self.pending_value = 0
        self.pending_block = None
        # For a pending non-local return, the frame it is aimed at.
        self.pending_frame = None

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
