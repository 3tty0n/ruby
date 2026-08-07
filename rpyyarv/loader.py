"""Load raw ISeqs into W_ISeqs, transforming operands by their insns.def type."""

import boot
import gcroots
import insns
import iseqdump
import optable
import rawiseq
import rubycall
import symbols
import value
from error import LoadError, UnsupportedOperation
from iseq import (CATCH_ENSURE, CATCH_RESCUE, NO_BLOCK_ISEQ, W_Catch,
                  W_CallInfo, W_ISeq)


# break/next/redo are implemented by the throw instruction unwinding an
# RPython exception, so their catch-table entries need no interpretation.
# retry is listed because the compiler emits an entry for it around every
# rescue clause whether or not the source says `retry`; the entry is dropped
# and `throw` with the retry tag is what refuses it.
IGNORED_CATCH_TYPES = ['break', 'next', 'redo', 'retry']

CATCH_KINDS = {'rescue': CATCH_RESCUE, 'ensure': CATCH_ENSURE}


class ConstPool(object):
    # Three pools, one per operand type: VALUEs are ints and cannot share a
    # list with W_ISeq or W_CallInfo.
    def __init__(self):
        self.consts = []
        self.iseqs = []
        self.callinfos = []
        self.paths = []         # constant paths, one list of ids each
        self.fixnums = {}       # integer -> index

    def add(self, v):
        self.consts.append(v)
        return len(self.consts) - 1

    def add_iseq(self, w_iseq):
        self.iseqs.append(w_iseq)
        return len(self.iseqs) - 1

    def add_callinfo(self, w_ci):
        self.callinfos.append(w_ci)
        return len(self.callinfos) - 1

    def add_path(self, ids):
        self.paths.append(ids)
        return len(self.paths) - 1

    def add_fixnum(self, n):
        if n in self.fixnums:
            return self.fixnums[n]
        idx = self.add(value.int2fix(n))
        self.fixnums[n] = idx
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
        w_iseq = self.load_iseq(0, [])
        gcroots.release_load_temporaries()
        return w_iseq

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

    def load_iseq(self, index, parents):
        """parents[0] is the enclosing ISeq, parents[1] its own, and so on:
        a getlocal at level N names a local of parents[N-1]."""
        if index in self.w_iseqs:
            return self.w_iseqs[index]
        if index < 0 or index >= len(self.program.iseqs):
            raise LoadError('iseq %d is not in the program' % index)
        raw = self.program.iseqs[index]

        for entry in raw.catches:
            if entry.kind not in CATCH_KINDS and \
                    entry.kind not in IGNORED_CATCH_TYPES:
                raise UnsupportedOperation(
                    "'%s' has a %s catch-table entry, which RPyYARV does not "
                    "support" % (raw.name, entry.kind))
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
                code[at] = self.operand(op, pos, ops, raw, pool,
                                        labels, parents)
                at += 1

        consts = [v for v in pool.consts]
        w_iseq = W_ISeq(raw.name, code, consts, [w for w in pool.iseqs],
                        [c for c in pool.callinfos], raw.nlocals,
                        raw.stack_max, raw.lead_num, raw.extra_params == '',
                        self.catches(raw, labels, parents),
                        [p for p in pool.paths])
        gcroots.register_consts(consts)
        self.w_iseqs[index] = w_iseq
        return w_iseq

    def catches(self, raw, labels, parents):
        """A rescue/ensure ISeq reads the enclosing scope's locals at level 1,
        so it is loaded with raw itself as its parent, the way a block is."""
        out = []
        for entry in raw.catches:
            if entry.kind not in CATCH_KINDS:
                continue
            if entry.iseq_index < 0:
                raise LoadError("a %s catch-table entry in '%s' has no ISeq"
                                % (entry.kind, raw.name))
            out.append(W_Catch(
                CATCH_KINDS[entry.kind],
                self.catch_label(entry.start, raw, labels),
                self.catch_label(entry.end, raw, labels),
                self.catch_label(entry.cont, raw, labels),
                entry.sp,
                self.load_iseq(entry.iseq_index, [raw] + parents)))
        return out

    def catch_label(self, name, raw, labels):
        if name not in labels:
            raise LoadError("a catch-table entry in '%s' names unknown label %s"
                            % (raw.name, name))
        return labels[name]

    def check_dropped(self, op, ops, raw):
        """Operand positions yarv_map.py does not emit, checked here."""
        if op == insns.GETLOCAL or op == insns.SETLOCAL:
            level = self.int_of(ops[1], op, raw, 'level')
            if level > optable.MAX_LOCAL_LEVEL:
                raise UnsupportedOperation(
                    "%s at level %d in '%s' reaches further out than the %d "
                    "scope(s) RPyYARV walks"
                    % (insns.NAMES[op], level, raw.name,
                       optable.MAX_LOCAL_LEVEL))
        elif op == insns.EXPANDARRAY:
            flag = self.int_of(ops[1], op, raw, 'flag')
            if flag != 0:
                raise UnsupportedOperation(
                    "expandarray with a splat or post arguments in '%s' is "
                    "not supported" % raw.name)
        elif op == insns.PUTSPECIALOBJECT:
            kind = self.int_of(ops[0], op, raw, 'object type')
            if kind < optable.SPECIAL_OBJECT_VMCORE or \
                    kind > optable.SPECIAL_OBJECT_CONST_BASE:
                raise UnsupportedOperation(
                    "putspecialobject %d in '%s' is not supported"
                    % (kind, raw.name))
        elif op == insns.DEFINECLASS:
            flags = self.int_of(ops[2], op, raw, 'flags')
            if flags & optable.DEFINECLASS_TYPE_MASK != \
                    optable.DEFINECLASS_TYPE_CLASS:
                raise UnsupportedOperation(
                    "'%s' defines a module or a singleton class, which "
                    "RPyYARV does not support" % raw.name)
            if flags & optable.DEFINECLASS_FLAG_SCOPED:
                raise UnsupportedOperation(
                    "'%s' defines a class under an explicit scope, which "
                    "RPyYARV does not support" % raw.name)

    def operand(self, op, pos, ops, raw, pool, labels, parents):
        operand = ops[pos]
        t = insns.OPERAND_TYPES[op][pos]
        if t == insns.T_VALUE:
            return self.literal(operand, op, raw, pool)
        if t == insns.T_LINDEX_T:
            level = self.int_of(ops[1], op, raw, 'level')
            return self.local_slot(operand, op, raw, parents, level)
        if t == insns.T_RB_NUM_T:
            return self.int_of(operand, op, raw, 'operand')
        if t == insns.T_OFFSET:
            return self.label(operand, op, raw, labels)
        if t == insns.T_ID:
            mid = symbols.intern(self.sym_of(operand, op, raw))
            if op == insns.GETINSTANCEVARIABLE or \
                    op == insns.SETINSTANCEVARIABLE:
                rubycall.rid(mid)       # intern the ivar's CRuby ID once
            return mid
        if t == insns.T_IC:
            return self.const_path(operand, op, raw, pool)
        if t == insns.T_ISEQ:
            if operand.kind == rawiseq.OP_NIL:
                return NO_BLOCK_ISEQ      # no block at this call site
            if operand.kind != rawiseq.OP_ISEQ:
                raise LoadError("%s in '%s' wants an ISeq, got %s"
                                % (insns.NAMES[op], raw.name,
                                   operand.describe()))
            return pool.add_iseq(
                self.load_iseq(operand.intval, [raw] + parents))
        if t == insns.T_CALL_DATA:
            return pool.add_callinfo(self.callinfo(operand, op, raw))
        raise LoadError("%s in '%s' has an operand of type %s, which "
                        "yarv_map.py supports but the loader does not"
                        % (insns.NAMES[op], raw.name, insns.TYPE_NAMES[t]))

    def const_path(self, operand, op, raw, pool):
        """An IC operand reaches to_a as the path's segments, one Symbol each
        (iseq.c:3503). An absolute `::Foo` has the empty name first."""
        if operand.kind != rawiseq.OP_ARRAY:
            raise LoadError("%s in '%s' wants a constant path, got %s"
                            % (insns.NAMES[op], raw.name, operand.describe()))
        if len(operand.items) == 0:
            raise LoadError("%s in '%s' has an empty constant path"
                            % (insns.NAMES[op], raw.name))
        ids = []
        for item in operand.items:
            ids.append(symbols.intern(self.sym_of(item, op, raw)))
        return pool.add_path(ids)

    def literal(self, operand, op, raw, pool):
        if operand.kind == rawiseq.OP_INT:
            return pool.add_fixnum(operand.intval)
        return pool.add(self.literal_value(operand, op, raw))

    def literal_value(self, operand, op, raw):
        """A real CRuby VALUE, built once at load time. Until its pool is
        registered it is reachable from nothing CRuby scans, so keepalive
        holds it across the rb_* calls the rest of the load makes."""
        v = self._literal_value(operand, op, raw)
        gcroots.keepalive(v)
        return v

    def _literal_value(self, operand, op, raw):
        kind = operand.kind
        if kind == rawiseq.OP_INT:
            if value.fixable(operand.intval):
                return value.int2fix(operand.intval)
            return boot.int2inum(operand.intval)
        if kind == rawiseq.OP_NIL:
            return value.Q_NIL
        if kind == rawiseq.OP_TRUE:
            return value.Q_TRUE
        if kind == rawiseq.OP_FALSE:
            return value.Q_FALSE
        if kind == rawiseq.OP_STR:
            return boot.str_new(operand.strval)
        if kind == rawiseq.OP_SYM:
            return boot.sym_new(operand.strval)
        if kind == rawiseq.OP_VALUE:
            return operand.intval
        if kind == rawiseq.OP_ARRAY:
            items = []
            for item in operand.items:
                items.append(self.literal_value(item, op, raw))
            return boot.ary_new(items)
        raise UnsupportedOperation(
            "%s of %s in '%s': RPyYARV has no such object yet"
            % (insns.NAMES[op], operand.describe(), raw.name))

    def local_slot(self, operand, op, raw, parents, level):
        idx = self.int_of(operand, op, raw, 'local index')
        # The index counts down from the top of the *naming* scope's
        # environment, which for a non-zero level is an enclosing ISeq.
        owner = raw
        if level > 0:
            if level > len(parents):
                raise LoadError("%s in '%s' reaches %d scope(s) out, past the "
                                "outermost one"
                                % (insns.NAMES[op], raw.name,
                                   level))
            owner = parents[level - 1]
        slot = owner.nlocals - idx + optable.ENV_DATA_SIZE - 1
        if slot < 0 or slot >= owner.nlocals:
            raise LoadError("%s in '%s' names local index %d, outside the %d "
                            "local(s) of '%s'"
                            % (insns.NAMES[op], raw.name, idx, owner.nlocals,
                               owner.name))
        if slot > optable.LOCAL_SLOT_MASK:
            raise LoadError("'%s' has more locals than one operand encodes"
                            % owner.name)
        return slot | (level << optable.LOCAL_LEVEL_SHIFT)

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
        # Not ARGS_SIMPLE itself: CRuby clears it whenever a block ISeq is
        # attached, and every other reason it can be clear (splat, block
        # argument, keywords, forwarding) has its own bit outside this mask.
        simple = (not operand.has_kwarg
                  and (flags & ~optable.SIMPLE_CALL_FLAGS) == 0)
        return W_CallInfo(symbols.intern(operand.strval), operand.intval,
                          simple, (flags & optable.CALL_FLAG_FCALL) != 0,
                          (flags & optable.CALL_FLAG_SUPER) != 0)

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
