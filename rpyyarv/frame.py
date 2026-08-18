from rpyyarv import value
from rpyyarv.rlib import hint

# Which throw a rescue/ensure ISeq runs under, so its trailing `throw 0` can continue it (vm_insnhelper.c:1733).
PENDING_NONE = 0
PENDING_RAISE = 1
PENDING_BREAK = 2
PENDING_NEXT = 3
PENDING_RETURN = 4
PENDING_RETRY = 5


class SharedLocals(object):
    """Locals a nested ISeq (block, rescue, once) can reach; on the heap, so a nested trace reads them without forcing this frame's virtualizable."""
    def __init__(self, n):
        self.values = [value.Q_NIL] * n


class Frame(object):
    # One per ISeq invocation, so Ruby call depth is RPython recursion depth.
    _virtualizable_ = ['sp', 'pc', 'stack[*]', 'locals[*]']
    _immutable_fields_ = ['shared']

    # VM_FRAME_FLAG_MODIFIED_BLOCK_PARAM (insns.def:111); left to the rtyper's zero-init so the common no-block-param call pays no store.
    block_param_set = False

    # A module body that ran `module_function` with no arguments; every def after it becomes private plus a singleton method (vm_method.c rb_mod_modfunc).
    module_func = False

    # A class/module body that ran `private` with no arguments; every def after it lands private, until `public` flips it back.
    private_pragma = False

    # Set on the way out of execute(); a `return` whose target frame is already gone is the orphaned Proc vm_throw_start answers with a LocalJumpError.
    dead = False

    # The gc_mark_state.generation that last marked this frame; block chains revisit frames, and one mark per collection is enough.
    marked_gen = 0

    # Almost every frame is a plain method call: no block, no unwind pending, not itself a block's frame. Zero-init covers all of that.
    block = None
    own_block = None
    defining_frame = None
    prev_frame = None
    pending_kind = PENDING_NONE
    pending_value = 0
    pending_block = None
    pending_frame = None

    def __init__(self, iseq, self_val, cref=None, entry=None):
        self = hint(self, access_directly=True, fresh_virtualizable=True)
        self.w_iseq = iseq
        self.stack = [0] * iseq.stack_max
        self.sp = 0
        # The pc of the running instruction, for finding a catch-table entry.
        self.pc = 0
        if iseq.shares_locals:
            self.locals = [value.Q_NIL] * 0
            self.shared = SharedLocals(iseq.nlocals)
        else:
            self.locals = [value.Q_NIL] * iseq.nlocals
            self.shared = None
        self.self_val = self_val
        # The interp.Cref a class body pushed, None outside one; its klass is what a def in the body lands on.
        self.cref = cref
        # The running MethodEntry, which invokesuper resumes above.
        self.entry = entry

    def local_get(self, idx):
        s = self.shared
        if s is not None:
            return s.values[idx]
        return self.locals[idx]

    def local_set(self, idx, v):
        s = self.shared
        if s is not None:
            s.values[idx] = v
        else:
            self.locals[idx] = v

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
