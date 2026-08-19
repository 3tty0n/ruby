from rpyyarv import value
from rpyyarv.rlib import hint

# Which throw the rescue/ensure ISeq runs under (vm_insnhelper.c:1733).
PENDING_NONE = 0
PENDING_RAISE = 1
PENDING_BREAK = 2
PENDING_NEXT = 3
PENDING_RETURN = 4
PENDING_RETRY = 5


class SharedLocals(object):
    """Heap locals a nested ISeq reads without forcing this virtualizable."""
    def __init__(self, n):
        self.values = [value.Q_NIL] * n


class Frame(object):
    # One per ISeq invocation, so Ruby call depth is RPython recursion depth.
    _virtualizable_ = ['sp', 'pc', 'stack[*]', 'locals[*]']
    _immutable_fields_ = ['shared']

    # VM_FRAME_FLAG_MODIFIED_BLOCK_PARAM (insns.def:111); zero-init, no store.
    block_param_set = False

    # Bare `module_function`: later defs go private + singleton (vm_method.c).
    module_func = False

    # Bare `private` in a class/module body: later defs land private.
    private_pragma = False

    # Set leaving execute(); `return` to a dead frame is a LocalJumpError.
    dead = False

    # Generation that last marked this frame; block chains revisit frames.
    marked_gen = 0

    # Almost every frame is a plain method call; zero-init covers all of it.
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
        # The Cref a class body pushed; its klass is where a def lands.
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
