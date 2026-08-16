"""The seam between front end and loader: iseqdump.py and bootiseq.py both fill these in; loader.py works on them without knowing which ran."""

# Flat kinds, not a class hierarchy: the loader takes the meaning from the operand's declared type in insns.def and never downcasts.
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
                 items=None, kw_names=None):
        self.kind = kind
        self.intval = intval
        self.strval = strval
        self.flag = flag
        self.has_kwarg = has_kwarg
        # The call site's literal keywords, in the order their values are pushed; empty when the front end reported none by name.
        self.kw_names = kw_names if kw_names is not None else []
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
    """[type, iseq, start, end, cont, sp], as iseq_data_to_ary spells it (iseq.c:3605); the three pc fields arrive as label names."""
    def __init__(self, kind, iseq_index=-1, start='', end='', cont='', sp=0):
        self.kind = kind        # 'rescue', 'ensure', 'break', ...
        self.iseq_index = iseq_index    # -1 when the entry has no ISeq
        self.start = start
        self.end = end
        self.cont = cont
        self.sp = sp


class RawISeq(object):
    def __init__(self, name, type_, nlocals, stack_max, lead_num,
                 extra_params, catches, opt_labels=None, rest_start=-1,
                 post_start=-1, post_num=0, ambiguous_param0=False,
                 kw_names=None, kw_required=0, kw_defaults=None,
                 kw_bits=-1, kwrest=-1):
        self.name = name
        self.type = type_
        self.nlocals = nlocals
        self.stack_max = stack_max
        self.lead_num = lead_num
        # Names of the other parameter kinds CRuby reported, if any.
        self.extra_params = extra_params
        self.catches = catches
        # iseq.c:3425 writes one label per optional plus one for "all given".
        self.opt_labels = opt_labels if opt_labels is not None else []
        # Local slots, as iseq.c:3438 spells them; -1 when the kind is absent.
        self.rest_start = rest_start
        self.post_start = post_start
        self.post_num = post_num
        # `{|a| }`, whose single parameter takes a yielded Array whole.
        self.ambiguous_param0 = ambiguous_param0
        # Keyword parameters (iseq.c:3442), required ones first; they occupy
        # the slots below kw_bits, which holds the unspecified-optionals mask.
        self.kw_names = kw_names if kw_names is not None else []
        self.kw_required = kw_required
        # One per keyword, None where the default is computed by the body.
        self.kw_defaults = kw_defaults if kw_defaults is not None else []
        self.kw_bits = kw_bits
        self.kwrest = kwrest
        # One name per local slot, '' for a slot with no name; only bootiseq.py fills it in, and only string eval reads it.
        self.local_names = []
        # Set by the loader on the first block or once operand it wires.
        self.shares_locals = False
        self.insns = []
        # Source line of each entry of insns; the bare Integers in iseq_data_to_ary's body set it.
        self.lines = []
        self.cur_line = 0
        # label name -> index into insns; the loader turns it into a pc.
        self.labels = {}
        # Enclosing ISeq, -1 for the outermost; the naming scope a getlocal at level 1 reaches. Only bootiseq.py fills it in.
        self.parent = -1

    def add_insn(self, insn):
        self.insns.append(insn)
        self.lines.append(self.cur_line)

    def set_line(self, n):
        self.cur_line = n

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
