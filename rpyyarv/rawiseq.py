"""The seam between front end and loader: ISeqs as CRuby spelled them.

iseqdump.py and bootiseq.py both fill these in; loader.py works on them
without knowing which ran. Nested ISeqs sit in one flat table addressed by
index, so no reader has to recurse.
"""

# Flat kinds rather than a class hierarchy: the loader picks the meaning from
# the operand's declared type in insns.def and never downcasts.
OP_INT = 0
OP_NIL = 1
OP_TRUE = 2
OP_FALSE = 3
OP_SYM = 4
OP_STR = 5
OP_ISEQ = 6     # intval indexes RawProgram.iseqs
OP_CALL = 7     # intval=orig_argc, flag=flags, strval=mid
OP_OTHER = 8
OP_ARRAY = 9    # items holds the elements
OP_VALUE = 10   # intval is a live CRuby VALUE the front end handed over

KIND_NAMES = ['Integer', 'nil', 'true', 'false', 'Symbol', 'String',
              'ISeq', 'call data', 'object', 'Array', 'object']


class RawOperand(object):
    def __init__(self, kind, intval=0, strval='', flag=0, has_kwarg=False,
                 items=None):
        self.kind = kind
        self.intval = intval
        self.strval = strval
        self.flag = flag
        self.has_kwarg = has_kwarg
        self.items = items if items is not None else []

    def describe(self):
        if self.kind == OP_ARRAY:
            return 'Array of %d' % len(self.items)
        if self.kind == OP_INT or self.kind == OP_ISEQ:
            return '%s %d' % (KIND_NAMES[self.kind], self.intval)
        if self.kind == OP_SYM or self.kind == OP_STR or \
                self.kind == OP_OTHER or self.kind == OP_VALUE:
            return '%s %s' % (KIND_NAMES[self.kind], self.strval)
        return KIND_NAMES[self.kind]


def int_operand(value):
    return RawOperand(OP_INT, value)


class RawInsn(object):
    def __init__(self, name, operands):
        self.name = name            # CRuby's spelling, e.g. 'getlocal_WC_0'
        self.operands = operands    # in insns.def order


class RawCatch(object):
    """One catch-table entry, as iseq_data_to_ary spells it (iseq.c:3605):
    [type, iseq, start, end, cont, sp]. The three pc fields arrive as label
    names, the same ones a jump operand carries."""
    def __init__(self, kind, iseq_index=-1, start='', end='', cont='', sp=0):
        self.kind = kind        # 'rescue', 'ensure', 'break', ...
        self.iseq_index = iseq_index    # -1 when the entry has no ISeq
        self.start = start
        self.end = end
        self.cont = cont
        self.sp = sp


class RawISeq(object):
    def __init__(self, name, type_, nlocals, stack_max, lead_num,
                 extra_params, catches):
        self.name = name
        self.type = type_
        self.nlocals = nlocals
        self.stack_max = stack_max
        self.lead_num = lead_num
        # Names of the other parameter kinds CRuby reported, if any.
        self.extra_params = extra_params
        # One RawCatch per catch-table entry, in the order CRuby searches it.
        self.catches = catches
        self.insns = []
        # label name -> index into insns; the loader turns it into a pc.
        self.labels = {}

    def add_insn(self, insn):
        self.insns.append(insn)

    def add_label(self, name):
        self.labels[name] = len(self.insns)


class RawProgram(object):
    def __init__(self, ruby_version='', path=''):
        self.ruby_version = ruby_version
        self.path = path
        self.iseqs = []             # index 0 is the outermost ISeq

    def add_iseq(self, raw):
        self.iseqs.append(raw)
        return len(self.iseqs) - 1
