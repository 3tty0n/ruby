from objects.base import W_Root


class W_ISeq(W_Root):
    # code is a flat list of ints: opcode followed by its operands.
    # Branch operands are absolute indices into code.
    def __init__(self, name, code, consts, nlocals, stack_max):
        self.name = name
        self.code = code
        self.consts = consts
        self.nlocals = nlocals
        self.stack_max = stack_max

    def repr(self):
        return '<W_ISeq %s>' % self.name
