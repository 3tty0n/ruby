from objects.transparent import w_nil


class Frame(object):
    def __init__(self, iseq):
        self.stack = [None] * iseq.stack_max
        self.sp = 0
        self.locals = [w_nil] * iseq.nlocals

    def push(self, w_x):
        self.stack[self.sp] = w_x
        self.sp += 1

    def pop(self):
        sp = self.sp - 1
        w_x = self.stack[sp]
        # Clear the vacated slot so dead references die; also the shape a
        # future virtualizable wants.
        self.stack[sp] = None
        self.sp = sp
        return w_x
