from objects.main import w_main
from objects.transparent import w_nil
from rlib import hint


class Frame(object):
    # One frame per ISeq invocation: a call recurses into interp.execute()
    # with a fresh Frame, so Ruby call depth is interpreter recursion depth.
    _virtualizable_ = ['sp', 'stack[*]', 'locals[*]']

    def __init__(self, iseq, w_self=w_main):
        self = hint(self, access_directly=True, fresh_virtualizable=True)
        self.stack = [None] * iseq.stack_max
        self.sp = 0
        self.locals = [w_nil] * iseq.nlocals
        self.w_self = w_self

    def push(self, w_x):
        sp = self.sp
        assert sp >= 0
        self.stack[sp] = w_x
        self.sp = sp + 1

    def pop(self):
        sp = self.sp - 1
        assert sp >= 0
        w_x = self.stack[sp]
        self.stack[sp] = None
        self.sp = sp
        return w_x
