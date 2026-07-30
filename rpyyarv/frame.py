from objects.main import w_main
from objects.transparent import w_nil


class Frame(object):
    # One frame per ISeq invocation: a call recurses into interp.execute()
    # with a fresh Frame, so Ruby call depth is interpreter recursion depth.
    def __init__(self, iseq, w_self=w_main):
        self.stack = [None] * iseq.stack_max
        self.sp = 0
        self.locals = [w_nil] * iseq.nlocals
        self.w_self = w_self

    def push(self, w_x):
        self.stack[self.sp] = w_x
        self.sp += 1

    def pop(self):
        sp = self.sp - 1
        w_x = self.stack[sp]
        self.stack[sp] = None       # the shape a virtualizable wants
        self.sp = sp
        return w_x
