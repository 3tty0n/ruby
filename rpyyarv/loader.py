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


# break/next/redo unwind as RPython exceptions; retry is here because the compiler emits an entry around every rescue clause regardless, and `throw` with the retry tag refuses it.
IGNORED_CATCH_TYPES = ['break', 'next', 'redo', 'retry']

CATCH_KINDS = {'rescue': CATCH_RESCUE, 'ensure': CATCH_ENSURE}


class ConstPool(object):
    # One pool per operand type: an RPython list of raw VALUE ints cannot also hold W_ISeq or W_CallInfo.
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


class LoadResult(object):
    """Root ISeq, how much of the program RPyYARV could represent, and why not the rest."""
    def __init__(self, w_iseq, total, supported, reasons):
        self.w_iseq = w_iseq
        self.total = total
        self.supported = supported
        self.reasons = reasons


class Loader(object):
    def __init__(self, program):
        self.program = program
        self.w_iseqs = {}           # program index -> W_ISeq
        self.reasons = []           # one per ISeq the loader gave up on

    def load(self):
        w_iseq = self.load_iseq(0, [])
        self.account_for_the_rest()
        gcroots.release_load_temporaries()
        supported = 0
        for index in self.w_iseqs:
            if self.w_iseqs[index].unsupported == '':
                supported += 1
        return LoadResult(w_iseq, len(self.program.iseqs), supported,
                          self.reasons)

    def account_for_the_rest(self):
        """An ISeq the loader gave up on never reached the ones nested in it, so without loading them too the coverage figure reads as one big failure."""
        if len(self.reasons) == 0:
            return
        for index in range(len(self.program.iseqs)):
            if index in self.w_iseqs:
                continue
            try:
                self.load_iseq(index, self.parents_of(index))
            except LoadError, e:
                self.w_iseqs[index] = self.stub(self.program.iseqs[index],
                                                e.msg)

    def parents_of(self, index):
        """The naming scopes around an ISeq, innermost first; empty for a front end that did not record them (rawiseq.RawISeq.parent)."""
        out = []
        at = self.program.iseqs[index].parent
        while at >= 0 and len(out) <= optable.MAX_LOCAL_LEVEL:
            out.append(self.program.iseqs[at])
            at = self.program.iseqs[at].parent
        return out

    def opcode_of(self, insn, raw):
        """The base opcode, or -1 when RPyYARV does not implement it."""
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
            return -1
        return op

    def operands_of(self, insn, op, raw):
        """Operands in insns.def order, with the ones a specialized variant fixes spliced back in from insns.SPEC_FILL."""
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
        """A getlocal at level N names a local of parents[N-1]; an unrepresentable ISeq becomes a stub, not a failed load, so the rest still loads for the CRuby fallback."""
        if index in self.w_iseqs:
            return self.w_iseqs[index]
        if index < 0 or index >= len(self.program.iseqs):
            raise LoadError('iseq %d is not in the program' % index)
        raw = self.program.iseqs[index]
        try:
            w_iseq = self.build_iseq(raw, parents)
        except UnsupportedOperation, e:
            w_iseq = self.stub(raw, e.msg)
        self.w_iseqs[index] = w_iseq
        return w_iseq

    def stub(self, raw, reason):
        self.reasons.append("'%s': %s" % (raw.name, reason))
        return W_ISeq(raw.name, [insns.LEAVE], [], [], [], raw.nlocals,
                      raw.stack_max, simple_params=False, unsupported=reason)

    def build_iseq(self, raw, parents):
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
                raise UnsupportedOperation("'%s' is not implemented"
                                           % insn.name)
            opcodes.append(op)
            operands.append(self.operands_of(insn, op, raw))
            starts.append(pc)
            pc += 1 + optable.NUM_OPERANDS[op]

        self.check_vmcore(opcodes, operands, raw)

        labels = {}
        for name in raw.labels:
            at = raw.labels[name]
            labels[name] = pc if at >= len(starts) else starts[at]

        # W_ISeq declares code and consts immutable, so neither may ever be resized; pc already holds the final length.
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

        opt_table = self.opt_table(raw, labels)
        if raw.extra_params != '':
            # Refused here, not at the send: a parameter shape the call path cannot place must fall back for the whole program, not raise on first call.
            raise UnsupportedOperation(
                "'%s' takes %s parameter(s), which RPyYARV does not support"
                % (raw.name, raw.extra_params))
        simple = (len(opt_table) == 0
                  and raw.rest_start < 0 and raw.post_num == 0)
        self.check_param_slots(raw, opt_table)
        opt_num = len(opt_table) - 1 if len(opt_table) > 0 else 0
        autosplat = (not raw.ambiguous_param0
                     and (raw.lead_num + raw.post_num > 0 or opt_num > 1))

        catches = self.catches(raw, labels, parents)
        returns = self.throws_return(opcodes, operands, raw, pool, catches)
        consts = [v for v in pool.consts]
        w_iseq = W_ISeq(raw.name, code, consts, [w for w in pool.iseqs],
                        [c for c in pool.callinfos], raw.nlocals,
                        raw.stack_max, raw.lead_num, simple,
                        catches,
                        [p for p in pool.paths], opt_table, raw.rest_start,
                        raw.post_start, raw.post_num, '', autosplat,
                        returns, returns and raw.type in self.RETURN_TARGETS)
        gcroots.register_consts(consts)
        return w_iseq

    # The ISeq types a non-local return may name; a class body gets LocalJumpError instead (vm_insnhelper.c:1893).
    RETURN_TARGETS = ['method', 'top', 'main']

    def throws_return(self, opcodes, operands, raw, pool, catches):
        """Whether a `return` from a block can reach here: this ISeq throws one, or something nested in it does."""
        for i in range(len(opcodes)):
            if opcodes[i] != insns.THROW:
                continue
            if self.int_of(operands[i][0], opcodes[i], raw, 'throw state') & \
                    optable.TAG_MASK == optable.TAG_RETURN:
                return True
        for w_child in pool.iseqs:
            if w_child.has_return_throw:
                return True
        for entry in catches:
            if entry.w_iseq.has_return_throw:
                return True
        return False

    # Everything the compiler may push between the FrozenCore receiver and the send that consumes it, for `alias` and `undef`.
    VMCORE_PUSHES = [insns.PUTSPECIALOBJECT, insns.PUTOBJECT, insns.PUTNIL,
                     insns.PUTSELF]
    VMCORE_SENDS = ['core#set_method_alias', 'core#undef_method']

    def check_vmcore(self, opcodes, operands, raw):
        """FrozenCore receives `alias`, `undef`, `lambda` and `proc` alike (vm.c:4274); only the first two are implemented, so the send taking it must be one of them."""
        for i in range(len(opcodes)):
            if opcodes[i] != insns.PUTSPECIALOBJECT:
                continue
            if self.int_of(operands[i][0], opcodes[i], raw, 'object type') != \
                    optable.SPECIAL_OBJECT_VMCORE:
                continue
            j = i + 1
            while j < len(opcodes) and opcodes[j] in self.VMCORE_PUSHES:
                j += 1
            mid = ''
            if j < len(opcodes) and (opcodes[j] == insns.SEND or
                                     opcodes[j] == insns.OPT_SEND_WITHOUT_BLOCK):
                mid = operands[j][0].strval
            if mid not in self.VMCORE_SENDS:
                raise UnsupportedOperation(
                    "RubyVM::FrozenCore#%s is not supported"
                    % (mid if mid != '' else '<unknown>'))

    def opt_table(self, raw, labels):
        """iseq.c:3425 writes opt_num+1 labels; anything shorter is not a table vm_args.c:906 could index."""
        if len(raw.opt_labels) == 0:
            return []
        if len(raw.opt_labels) < 2:
            raise LoadError("'%s' has a %d-entry opt table"
                            % (raw.name, len(raw.opt_labels)))
        out = []
        for name in raw.opt_labels:
            if name not in labels:
                raise LoadError("the opt table of '%s' names unknown label %s"
                                % (raw.name, name))
            out.append(labels[name])
        return out

    def check_param_slots(self, raw, opt_table):
        opt_num = len(opt_table) - 1 if len(opt_table) > 0 else 0
        top = raw.lead_num + opt_num
        if raw.rest_start >= 0:
            top = raw.rest_start + 1
        if raw.post_num > 0:
            top = raw.post_start + raw.post_num
        if top > raw.nlocals:
            raise LoadError("'%s' takes %d parameter(s) but has %d local(s)"
                            % (raw.name, top, raw.nlocals))

    def catches(self, raw, labels, parents):
        """A catch ISeq reads the enclosing locals at level 1, so raw itself is its parent, the way a block's is."""
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

    # Everything whose lindex_t operand carries a level yarv_map.py packs.
    LOCAL_OPS = [insns.GETLOCAL, insns.SETLOCAL, insns.GETBLOCKPARAM,
                 insns.SETBLOCKPARAM, insns.GETBLOCKPARAMPROXY]

    def check_dropped(self, op, ops, raw):
        """Operand positions yarv_map.py does not emit, checked here."""
        if op in self.LOCAL_OPS:
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
        elif op == insns.THROW:
            tag = self.int_of(ops[0], op, raw, 'throw state') & \
                optable.TAG_MASK
            if tag == optable.TAG_RETRY:
                raise UnsupportedOperation('retry is not supported')
            if tag == optable.TAG_REDO:
                raise UnsupportedOperation('redo is not supported')
        elif op == insns.INVOKESUPER:
            if ops[1].kind != rawiseq.OP_NIL:
                raise UnsupportedOperation(
                    'super with a block is not supported')
        elif op == insns.PUTSPECIALOBJECT:
            kind = self.int_of(ops[0], op, raw, 'object type')
            if kind < optable.SPECIAL_OBJECT_VMCORE or \
                    kind > optable.SPECIAL_OBJECT_CONST_BASE:
                raise UnsupportedOperation(
                    "putspecialobject %d in '%s' is not supported"
                    % (kind, raw.name))
        elif op == insns.DEFINECLASS:
            flags = self.int_of(ops[2], op, raw, 'flags')
            kind = flags & optable.DEFINECLASS_TYPE_MASK
            if kind == optable.DEFINECLASS_TYPE_SINGLETON_CLASS:
                # `def self.x` is definesmethod and runs; a `class << self` body needs the singleton class as a cref, which these frames do not carry.
                raise UnsupportedOperation(
                    "'%s' opens a singleton class body, which RPyYARV does "
                    "not support" % raw.name)
            if kind != optable.DEFINECLASS_TYPE_CLASS:
                raise UnsupportedOperation(
                    "'%s' defines a module, which RPyYARV does not support"
                    % raw.name)
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
        """An IC reaches to_a as one Symbol per path segment (iseq.c:3503); an absolute `::Foo` has the empty name first."""
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
        """A real CRuby VALUE: until its pool is registered nothing CRuby scans reaches it, hence the keepalive."""
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
        # The index counts down from the top of the *naming* scope's environment, an enclosing ISeq when level is non-zero.
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
        # Not ARGS_SIMPLE itself: CRuby clears it whenever a block ISeq is attached, and every other reason has its own bit outside this mask.
        simple = (not operand.has_kwarg
                  and (flags & ~optable.SIMPLE_CALL_FLAGS) == 0)
        if not simple:
            # Refused here, not at the send: an ISeq holding a call site the interpreter cannot make is one it cannot finish running.
            raise UnsupportedOperation(
                "the call to '%s' passes %s, which RPyYARV does not support"
                % (operand.strval, self.call_flag_name(operand)))
        blockarg = (flags & optable.CALL_FLAG_ARGS_BLOCKARG) != 0
        if blockarg and (flags & optable.CALL_FLAG_SUPER) != 0:
            raise UnsupportedOperation('super with a block is not supported')
        return W_CallInfo(symbols.intern(operand.strval), operand.intval,
                          simple, (flags & optable.CALL_FLAG_FCALL) != 0,
                          (flags & optable.CALL_FLAG_SUPER) != 0, blockarg)

    def call_flag_name(self, operand):
        for flag, name in optable.CALL_FLAG_NAMES:
            if operand.flag & flag:
                return name
        if operand.has_kwarg:
            return 'keyword'
        return 'arguments'

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


def load_strict(program):
    """RPyYARV's own code, which it must be able to run: no CRuby fallback."""
    result = load(program)
    if len(result.reasons) > 0:
        raise UnsupportedOperation('; '.join(result.reasons))
    return result.w_iseq


def load_dump(text):
    """The only format-aware entry point; no CRuby to fall back to here, so it refuses what it cannot load."""
    return load_strict(iseqdump.parse(text))
