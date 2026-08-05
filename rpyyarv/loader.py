"""Load raw ISeqs into W_ISeqs, transforming operands by their insns.def type."""

import insns
import iseqdump
import optable
import rawiseq
import symbols
from error import LoadError, UnsupportedOperation
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from objects.array import W_Array
from objects.string import W_String
from objects.transparent import W_Fixnum, w_nil, w_true, w_false


class ConstPool(object):
    def __init__(self):
        self.consts = []
        self.fixnums = {}       # value -> index

    def add(self, w_x):
        self.consts.append(w_x)
        return len(self.consts) - 1

    def add_fixnum(self, value):
        if value in self.fixnums:
            return self.fixnums[value]
        idx = self.add(W_Fixnum(value))
        self.fixnums[value] = idx
        return idx


class Loader(object):
    def __init__(self, program):
        self.program = program
        self.missing = {}           # unimplemented name -> occurrences
        self.missing_names = []     # first seen first, for a stable report
        self.w_iseqs = {}           # program index -> W_ISeq

    def load(self):
        self.scan()
        if len(self.missing_names) > 0:
            raise UnsupportedOperation(self.report())
        return self.load_iseq(0)

    def scan(self):
        for raw in self.program.iseqs:
            for insn in raw.insns:
                self.opcode_of(insn, raw)

    def report(self):
        parts = []
        total = 0
        for name in self.missing_names:
            count = self.missing[name]
            total += count
            parts.append('%s x%d' % (name, count))
        return ('%d unimplemented instruction(s) in %d occurrence(s): %s'
                % (len(self.missing_names), total, ', '.join(parts)))

    def opcode_of(self, insn, raw):
        """The base opcode, or -1 once the name is counted as missing."""
        name = insn.name
        if name.startswith(insns.TRACE_PREFIX):
            raise UnsupportedOperation(
                "instruction '%s' in '%s' comes from a TracePoint-enabled "
                "build, which RPyYARV does not support" % (name, raw.name))
        if name in insns.SPEC_BASE:
            op = insns.SPEC_BASE[name]
        elif name in insns.NAME_TO_OP:
            op = insns.NAME_TO_OP[name]
        else:
            raise LoadError(
                "'%s' in '%s' is not an instruction in insns.def; the input "
                "and insns.py come from different rubies"
                % (name, raw.name))
        if not optable.IMPLEMENTED[op]:
            if name in self.missing:
                self.missing[name] = self.missing[name] + 1
            else:
                self.missing[name] = 1
                self.missing_names.append(name)
            return -1
        return op

    def operands_of(self, insn, op, raw):
        """Operands in insns.def order, with the ones a specialized variant
        fixes spliced back in from insns.SPEC_FILL."""
        want = len(insns.OPERAND_TYPES[op])
        given = insn.operands
        if insn.name not in insns.SPEC_FILL:
            if len(given) != want:
                raise LoadError(
                    "'%s' in '%s' has %d operand(s), insns.def says %d"
                    % (insn.name, raw.name, len(given), want))
            return given

        fill = insns.SPEC_FILL[insn.name]
        operands = []
        taken = 0
        for pos in range(want):
            value = 0
            filled = False
            for pair in fill:
                if pair[0] == pos:
                    value = pair[1]
                    filled = True
            if filled:
                operands.append(rawiseq.int_operand(value))
            elif taken < len(given):
                operands.append(given[taken])
                taken += 1
            else:
                raise LoadError("'%s' in '%s' is missing operand %d"
                                % (insn.name, raw.name, pos))
        if taken != len(given):
            raise LoadError("'%s' in '%s' has %d operand(s) too many"
                            % (insn.name, raw.name, len(given) - taken))
        return operands

    def load_iseq(self, index):
        if index in self.w_iseqs:
            return self.w_iseqs[index]
        if index < 0 or index >= len(self.program.iseqs):
            raise LoadError('iseq %d is not in the program' % index)
        raw = self.program.iseqs[index]

        if raw.catch_size > 0:
            raise UnsupportedOperation(
                "'%s' has a catch table (rescue/ensure/retry/next/break), "
                "which RPyYARV does not support" % raw.name)
        if raw.lead_num > raw.nlocals:
            raise LoadError("'%s' takes %d parameter(s) but has %d local(s)"
                            % (raw.name, raw.lead_num, raw.nlocals))

        # Widths first: a jump needs the pc of a later instruction.
        opcodes = []
        operands = []
        starts = []
        pc = 0
        for insn in raw.insns:
            op = self.opcode_of(insn, raw)
            if op < 0:
                raise UnsupportedOperation(self.report())
            opcodes.append(op)
            operands.append(self.operands_of(insn, op, raw))
            starts.append(pc)
            pc += 1 + optable.NUM_OPERANDS[op]

        labels = {}
        for name in raw.labels:
            at = raw.labels[name]
            labels[name] = pc if at >= len(starts) else starts[at]

        # W_ISeq declares code and consts immutable, so both have to reach it
        # as lists that were never resized: pc already holds the final length.
        pool = ConstPool()
        code = [0] * pc
        at = 0
        for i in range(len(opcodes)):
            op = opcodes[i]
            ops = operands[i]
            self.check_dropped(op, ops, raw)
            code[at] = op
            at += 1
            for pos in optable.EMIT_POSITIONS[op]:
                code[at] = self.operand(op, pos, ops[pos], raw, pool, labels)
                at += 1

        w_iseq = W_ISeq(raw.name, code, [w for w in pool.consts], raw.nlocals,
                        raw.stack_max, raw.lead_num, raw.extra_params == '')
        self.w_iseqs[index] = w_iseq
        return w_iseq

    def check_dropped(self, op, ops, raw):
        """Operand positions yarv_map.py does not emit, checked here."""
        if op == insns.GETLOCAL or op == insns.SETLOCAL:
            level = self.int_of(ops[1], op, raw, 'level')
            if level > optable.MAX_LOCAL_LEVEL:
                raise UnsupportedOperation(
                    "%s at level %d in '%s' reaches an enclosing scope, which "
                    "RPyYARV does not support"
                    % (insns.NAMES[op], level, raw.name))
        elif op == insns.EXPANDARRAY:
            flag = self.int_of(ops[1], op, raw, 'flag')
            if flag != 0:
                raise UnsupportedOperation(
                    "expandarray with a splat or post arguments in '%s' is "
                    "not supported" % raw.name)

    def operand(self, op, pos, operand, raw, pool, labels):
        t = insns.OPERAND_TYPES[op][pos]
        if t == insns.T_VALUE:
            return self.literal(operand, op, raw, pool)
        if t == insns.T_LINDEX_T:
            return self.local_slot(operand, op, raw)
        if t == insns.T_RB_NUM_T:
            return self.int_of(operand, op, raw, 'operand')
        if t == insns.T_OFFSET:
            return self.label(operand, op, raw, labels)
        if t == insns.T_ID:
            return symbols.intern(self.sym_of(operand, op, raw))
        if t == insns.T_ISEQ:
            if operand.kind == rawiseq.OP_NIL:
                return NO_BLOCK_ISEQ      # no block at this call site
            if operand.kind != rawiseq.OP_ISEQ:
                raise LoadError("%s in '%s' wants an ISeq, got %s"
                                % (insns.NAMES[op], raw.name,
                                   operand.describe()))
            return pool.add(self.load_iseq(operand.intval))
        if t == insns.T_CALL_DATA:
            return pool.add(self.callinfo(operand, op, raw))
        raise LoadError("%s in '%s' has an operand of type %s, which "
                        "yarv_map.py supports but the loader does not"
                        % (insns.NAMES[op], raw.name, insns.TYPE_NAMES[t]))

    def literal(self, operand, op, raw, pool):
        if operand.kind == rawiseq.OP_INT:
            return pool.add_fixnum(operand.intval)
        return pool.add(self.literal_value(operand, op, raw))

    def literal_value(self, operand, op, raw):
        kind = operand.kind
        if kind == rawiseq.OP_INT:
            return W_Fixnum(operand.intval)
        if kind == rawiseq.OP_NIL:
            return w_nil
        if kind == rawiseq.OP_TRUE:
            return w_true
        if kind == rawiseq.OP_FALSE:
            return w_false
        if kind == rawiseq.OP_STR:
            return W_String(operand.strval)
        if kind == rawiseq.OP_ARRAY:
            items_w = []
            for item in operand.items:
                items_w.append(self.literal_value(item, op, raw))
            return W_Array(items_w)
        raise UnsupportedOperation(
            "%s of %s in '%s': RPyYARV has no such object yet"
            % (insns.NAMES[op], operand.describe(), raw.name))

    def local_slot(self, operand, op, raw):
        idx = self.int_of(operand, op, raw, 'local index')
        slot = raw.nlocals - idx + optable.ENV_DATA_SIZE - 1
        if slot < 0 or slot >= raw.nlocals:
            raise LoadError("%s in '%s' names local index %d, outside its %d "
                            "local(s)"
                            % (insns.NAMES[op], raw.name, idx, raw.nlocals))
        return slot

    def label(self, operand, op, raw, labels):
        if operand.kind != rawiseq.OP_SYM:
            raise LoadError("%s in '%s' wants a label, got %s"
                            % (insns.NAMES[op], raw.name, operand.describe()))
        name = operand.strval
        if name not in labels:
            raise LoadError("%s in '%s' jumps to unknown label %s"
                            % (insns.NAMES[op], raw.name, name))
        return labels[name]

    def callinfo(self, operand, op, raw):
        if operand.kind != rawiseq.OP_CALL:
            raise LoadError("%s in '%s' wants call data, got %s"
                            % (insns.NAMES[op], raw.name, operand.describe()))
        flags = operand.flag
        simple = (not operand.has_kwarg
                  and (flags & ~optable.SIMPLE_CALL_FLAGS) == 0
                  and (flags & optable.CALL_FLAG_ARGS_SIMPLE) != 0)
        return W_CallInfo(symbols.intern(operand.strval), operand.intval,
                          simple, (flags & optable.CALL_FLAG_FCALL) != 0)

    def int_of(self, operand, op, raw, what):
        if operand.kind != rawiseq.OP_INT:
            raise LoadError("%s in '%s' wants an integer %s, got %s"
                            % (insns.NAMES[op], raw.name, what,
                               operand.describe()))
        return operand.intval

    def sym_of(self, operand, op, raw):
        if operand.kind != rawiseq.OP_SYM:
            raise LoadError("%s in '%s' wants a name, got %s"
                            % (insns.NAMES[op], raw.name, operand.describe()))
        return operand.strval


def load(program):
    return Loader(program).load()


def load_dump(text):
    """The only format-aware entry point; the boot path calls load()."""
    return load(iseqdump.parse(text))
