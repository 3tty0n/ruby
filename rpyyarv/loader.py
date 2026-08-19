"""Load raw ISeqs into W_ISeqs, transforming operands by insns.def type."""

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import gcroots
from rpyyarv import insns
from rpyyarv import iseqdump
from rpyyarv import optable
from rpyyarv import rawiseq
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import LoadError, UnsupportedOperation
from rpyyarv.iseq import (CATCH_ENSURE, CATCH_RESCUE, CATCH_RETRY,
                          NO_BLOCK_ISEQ, W_Catch,
                  W_CallInfo, W_ISeq)


# break/next/redo unwind as RPython exceptions; `throw` refuses the retry tag.
IGNORED_CATCH_TYPES = ['break', 'next', 'redo']

CATCH_KINDS = {'rescue': CATCH_RESCUE, 'ensure': CATCH_ENSURE,
               'retry': CATCH_RETRY}


class ConstPool(object):
    # One pool per type: a list of VALUE ints cannot hold W_ISeq or W_CallInfo.
    def __init__(self):
        self.consts = []
        self.iseqs = []
        self.callinfos = []
        self.paths = []         # constant paths, one list of ids each
        self.case_tables = []   # Integer literal -> destination pc
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

    def add_case_table(self, table):
        self.case_tables.append(table)
        return len(self.case_tables) - 1

    def add_fixnum(self, n):
        if n in self.fixnums:
            return self.fixnums[n]
        idx = self.add(value.int2fix(n))
        self.fixnums[n] = idx
        return idx


class LoadResult(object):
    """Root ISeq, how much RPyYARV could represent, and why not the rest."""
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
        """A skipped ISeq hides the ones nested in it from the coverage."""
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
        """Naming scopes around an ISeq, innermost first (RawISeq.parent)."""
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
        """Operands in insns.def order, specialized ones from SPEC_FILL."""
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
        """A getlocal at level N names a local of parents[N-1]."""
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
                      raw.stack_max, simple_params=False, unsupported=reason,
                      path=self.program.path)

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

        # Only where the line changes: one pair per source line, not per insn.
        line_pcs = []
        line_nums = []
        for i in range(len(starts)):
            n = raw.lines[i] if i < len(raw.lines) else 0
            if len(line_nums) == 0 or line_nums[len(line_nums) - 1] != n:
                line_pcs.append(starts[i])
                line_nums.append(n)

        # W_ISeq declares code and consts immutable: neither may be resized.
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
            # Refused here, not at the send: fall back for the whole program.
            raise UnsupportedOperation(
                "'%s' takes %s parameter(s), which RPyYARV does not support"
                % (raw.name, raw.extra_params))
        kw_table, kw_defaults, kw_start = self.keywords(raw, pool)
        simple = (len(opt_table) == 0
                  and raw.rest_start < 0 and raw.post_num == 0
                  and len(kw_table) == 0 and raw.kwrest < 0)
        self.check_param_slots(raw, opt_table)
        opt_num = len(opt_table) - 1 if len(opt_table) > 0 else 0
        autosplat = (not raw.ambiguous_param0
                     and (raw.lead_num + raw.post_num > 0 or opt_num > 1))

        catches = self.catches(raw, labels, parents)
        returns = self.throws_return(opcodes, operands, raw, pool, catches)
        shares = raw.shares_locals
        for entry in catches:
            # A rescue/ensure ISeq reads `$!` and locals via defining_frame.
            if entry.w_iseq is not None:
                shares = True
        consts = [v for v in pool.consts]
        w_iseq = W_ISeq(raw.name, code, consts, [w for w in pool.iseqs],
                        [c for c in pool.callinfos], raw.nlocals,
                        raw.stack_max, raw.lead_num, simple,
                        catches,
                        [p for p in pool.paths], opt_table, raw.rest_start,
                        raw.post_start, raw.post_num, '', autosplat,
                        returns, returns and raw.type in self.RETURN_TARGETS,
                        [dispatch.new_const_site() for _ in pool.paths],
                        kw_table, kw_defaults, raw.kw_required, kw_start,
                        raw.kw_bits, raw.kwrest, self.program.path,
                        [t for t in pool.case_tables],
                        [p for p in line_pcs], [n for n in line_nums],
                        shares, [n for n in raw.local_names])
        if raw.forwardable:
            # The `...` rest carries keywords the ruby2_keywords way.
            w_iseq.r2k = True
        gcroots.register_consts(consts)
        # The `once` cache lives here; the mark hook walks the list.
        gcroots.register_consts(w_iseq.once_cache)
        return w_iseq

    # ISeq types a non-local return may name (vm_insnhelper.c:1893).
    RETURN_TARGETS = ['method', 'top', 'main']

    def throws_return(self, opcodes, operands, raw, pool, catches):
        """Whether a `return` from a block can reach here, direct or nested."""
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
            if entry.w_iseq is not None and entry.w_iseq.has_return_throw:
                return True
        return False

    # Ordinary public sends, so rb_funcallv runs them.
    VMCORE_SENDS = ['core#set_method_alias', 'core#undef_method',
                    'core#set_variable_alias',
                    'core#hash_merge_ptr', 'core#hash_merge_kwd',
                    'lambda']

    def check_vmcore(self, opcodes, operands, raw):
        """FrozenCore's consumer send (vm.c:4274) must be an implemented one."""
        for i in range(len(opcodes)):
            if opcodes[i] != insns.PUTSPECIALOBJECT:
                continue
            if self.int_of(operands[i][0], opcodes[i], raw, 'object type') != \
                    optable.SPECIAL_OBJECT_VMCORE:
                continue
            # Walk the stack depth to the send whose receiver this push is;
            # anything inconclusive defers to the runtime's receiver guard.
            depth = 1
            j = i + 1
            while j < len(opcodes):
                op = opcodes[j]
                if op == insns.SEND or op == insns.OPT_SEND_WITHOUT_BLOCK:
                    ci = operands[j][0]
                    pops = ci.intval + len(ci.kw_names) + 1
                    if ci.flag & optable.CALL_FLAG_ARGS_BLOCKARG:
                        pops += 1
                    if depth == pops:
                        if ci.strval not in self.VMCORE_SENDS:
                            raise UnsupportedOperation(
                                "RubyVM::FrozenCore#%s is not supported"
                                % ci.strval)
                        break
                    if depth < pops:
                        break
                    depth += 1 - pops
                elif insns.IS_BRANCH[op] or op == insns.JUMP \
                        or op == insns.LEAVE or op == insns.THROW:
                    break
                else:
                    pop = insns.STACK_POP[op]
                    push = insns.STACK_PUSH[op]
                    if pop < 0 or push < 0:
                        break
                    depth += push - pop
                    if depth <= 0:
                        break
                j += 1

    def opt_table(self, raw, labels):
        """iseq.c:3425 writes opt_num+1 labels; vm_args.c:906 indexes them."""
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

    def keywords(self, raw, pool):
        """Keyword ids, static defaults (Qundef if computed), first slot."""
        if len(raw.kw_names) == 0:
            if raw.kwrest >= 0 and (raw.kwrest >= raw.nlocals):
                raise LoadError("'%s' puts **rest in slot %d, outside its %d "
                                "local(s)"
                                % (raw.name, raw.kwrest, raw.nlocals))
            return [], [], -1
        if len(raw.kw_names) > optable.KW_SPECIFIED_BITS_MAX:
            raise UnsupportedOperation(
                "'%s' takes %d keyword parameter(s); past %d CRuby keeps the "
                "unspecified mask in a Hash, which RPyYARV does not read"
                % (raw.name, len(raw.kw_names),
                   optable.KW_SPECIFIED_BITS_MAX))
        kw_start = raw.kw_bits - len(raw.kw_names)
        if kw_start < 0 or raw.kw_bits >= raw.nlocals or \
                (raw.kwrest >= 0 and raw.kwrest >= raw.nlocals):
            raise LoadError("'%s' puts its keyword parameters outside its %d "
                            "local(s)" % (raw.name, raw.nlocals))
        table = []
        defaults = []
        for name in raw.kw_names:
            table.append(symbols.intern(name))
        for operand in raw.kw_defaults:
            if operand is None:
                defaults.append(value.Q_UNDEF)
            else:
                v = self.literal_value(operand, insns.PUTOBJECT, raw)
                # Into the pool too, so gcroots keeps it alive for the run.
                pool.add(v)
                defaults.append(v)
        # Copied: W_ISeq declares both immutable, so neither may be resizable.
        return [m for m in table], [d for d in defaults], kw_start

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
        """A catch ISeq reads enclosing locals at level 1: raw is its parent."""
        n = 0
        for entry in raw.catches:
            if entry.kind in CATCH_KINDS:
                n += 1
        out = [None] * n
        at = 0
        for entry in raw.catches:
            if entry.kind not in CATCH_KINDS:
                continue
            if entry.kind == 'retry':
                out[at] = W_Catch(
                    CATCH_RETRY,
                    self.catch_label(entry.start, raw, labels),
                    self.catch_label(entry.end, raw, labels),
                    self.catch_label(entry.cont, raw, labels),
                    entry.sp, None)
                at += 1
                continue
            if entry.iseq_index < 0:
                raise LoadError("a %s catch-table entry in '%s' has no ISeq"
                                % (entry.kind, raw.name))
            out[at] = W_Catch(
                CATCH_KINDS[entry.kind],
                self.catch_label(entry.start, raw, labels),
                self.catch_label(entry.end, raw, labels),
                self.catch_label(entry.cont, raw, labels),
                entry.sp,
                self.load_iseq(entry.iseq_index, [raw] + parents))
            at += 1
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
            if flag & ~3:
                raise UnsupportedOperation(
                    "expandarray flag %d in '%s' is not supported"
                    % (flag, raw.name))
        elif op == insns.THROW:
            tag = self.int_of(ops[0], op, raw, 'throw state') & \
                optable.TAG_MASK
            if tag == optable.TAG_REDO:
                raise UnsupportedOperation('redo is not supported')
        elif op == insns.SENDFORWARD or op == insns.INVOKESUPERFORWARD:
            if ops[1].kind != rawiseq.OP_NIL:
                raise UnsupportedOperation(
                    'a written block on a forwarding call is not supported')
        elif op == insns.PUTSPECIALOBJECT:
            kind = self.int_of(ops[0], op, raw, 'object type')
            if kind < optable.SPECIAL_OBJECT_VMCORE or \
                    kind > optable.SPECIAL_OBJECT_CONST_BASE:
                raise UnsupportedOperation(
                    "putspecialobject %d in '%s' is not supported"
                    % (kind, raw.name))
        elif op == insns.GETSPECIAL:
            key = self.int_of(ops[0], op, raw, 'key')
            if key != 1:
                raise UnsupportedOperation(
                    "getspecial key %d in '%s' is not supported"
                    % (key, raw.name))
        elif op == insns.OPT_DUPARRAY_SEND:
            if self.int_of(ops[2], op, raw, 'argc') != 1:
                raise UnsupportedOperation(
                    "opt_duparray_send in '%s' takes an argument count "
                    "RPyYARV does not support" % raw.name)
        elif op == insns.OPT_NEWARRAY_SEND:
            meth = self.int_of(ops[1], op, raw, 'method')
            argc = -1
            if meth >= 1 and meth <= len(optable.NEWARRAY_SEND_ARGC):
                argc = optable.NEWARRAY_SEND_ARGC[meth - 1]
            if argc < 0 or self.int_of(ops[0], op, raw, 'length') < argc:
                raise UnsupportedOperation(
                    "opt_newarray_send %d in '%s' is not supported"
                    % (meth, raw.name))
        elif op == insns.DEFINECLASS:
            flags = self.int_of(ops[2], op, raw, 'flags')
            kind = flags & optable.DEFINECLASS_TYPE_MASK
            if kind != optable.DEFINECLASS_TYPE_CLASS and \
                    kind != optable.DEFINECLASS_TYPE_MODULE and \
                    kind != optable.DEFINECLASS_TYPE_SINGLETON_CLASS:
                raise UnsupportedOperation(
                    "'%s' uses defineclass type %d, which RPyYARV does not "
                    "support" % (raw.name, kind))

    def operand(self, op, pos, ops, raw, pool, labels, parents):
        operand = ops[pos]
        t = insns.OPERAND_TYPES[op][pos]
        if t == insns.T_VALUE:
            return self.literal(operand, op, raw, pool)
        if t == insns.T_LINDEX_T:
            if op == insns.CHECKKEYWORD:
                # Only operand 0 names a local; operand 1 is a bit number.
                if pos == 1:
                    return self.int_of(operand, op, raw, 'keyword index')
                return self.local_slot(operand, op, raw, parents, 0)
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
        if t == insns.T_CDHASH:
            return pool.add_case_table(
                self.case_table(operand, op, raw, labels))
        if t == insns.T_ISEQ:
            if operand.kind == rawiseq.OP_NIL:
                return NO_BLOCK_ISEQ      # no block at this call site
            if operand.kind != rawiseq.OP_ISEQ:
                raise LoadError("%s in '%s' wants an ISeq, got %s"
                                % (insns.NAMES[op], raw.name,
                                   operand.describe()))
            if op == insns.SEND or op == insns.INVOKESUPER \
                    or op == insns.ONCE:
                # The nested ISeq shares these locals: they move to the heap.
                raw.shares_locals = True
            return pool.add_iseq(
                self.load_iseq(operand.intval, [raw] + parents))
        if t == insns.T_CALL_DATA:
            return pool.add_callinfo(self.callinfo(operand, op, raw))
        raise LoadError("%s in '%s' has an operand of type %s, which "
                        "yarv_map.py supports but the loader does not"
                        % (insns.NAMES[op], raw.name, insns.TYPE_NAMES[t]))

    def case_table(self, operand, op, raw, labels):
        """The Fixnum entries of CRuby's alternating [literal, label] CDHASH."""
        if operand.kind != rawiseq.OP_ARRAY or len(operand.items) % 2 != 0:
            raise LoadError("%s in '%s' has a malformed case table"
                            % (insns.NAMES[op], raw.name))
        table = {}
        i = 0
        while i < len(operand.items):
            key = operand.items[i]
            target = operand.items[i + 1]
            if key.kind == rawiseq.OP_INT and key.intval not in table:
                table[key.intval] = self.label(target, op, raw, labels)
            i += 2
        return table

    def const_path(self, operand, op, raw, pool):
        """One Symbol per segment (iseq.c:3503); `::Foo` leads with empty."""
        if operand.kind != rawiseq.OP_ARRAY:
            raise LoadError("%s in '%s' wants a constant path, got %s"
                            % (insns.NAMES[op], raw.name, operand.describe()))
        if len(operand.items) == 0:
            raise LoadError("%s in '%s' has an empty constant path"
                            % (insns.NAMES[op], raw.name))
        ids = []
        for item in operand.items:
            name = self.sym_of(item, op, raw)
            ids.append(symbols.intern(name))
        return pool.add_path(ids)

    def literal(self, operand, op, raw, pool):
        if operand.kind == rawiseq.OP_INT:
            return pool.add_fixnum(operand.intval)
        v = self.literal_value(operand, op, raw)
        if op == insns.OPT_STR_FREEZE:
            # Frozen once here, so the instruction is just a push.
            v = rubycall.call0(v, symbols.intern('freeze'))
        return pool.add(v)

    def literal_value(self, operand, op, raw):
        """Until the pool is registered nothing CRuby scans reaches it."""
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
        # The index counts down from the top of the naming scope's environment.
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
        if operand.intval == 1 and (operand.strval == 'refine'
                                    or operand.strval == 'using'):
            # Refinements are lexical; RPyYARV's dispatch never consults them.
            raise UnsupportedOperation(
                "the call to '%s' needs CRuby's lexical refinements"
                % operand.strval)
        flags = operand.flag
        argc_extra = 0
        if flags & optable.CALL_FLAG_FORWARDING:
            if op == insns.OPT_NEW:
                # opt_new's argc already counts the `...` slot on the stack.
                flags &= ~optable.CALL_FLAG_FORWARDING
            else:
                # f(...): the `...` rest local is on the stack; run f(*rest).
                flags = (flags & ~optable.CALL_FLAG_FORWARDING) | \
                    optable.CALL_FLAG_ARGS_SPLAT
                if op == insns.SENDFORWARD:
                    # Blockarg-shaped: a forwarded break unwinds past here.
                    flags |= optable.CALL_FLAG_ARGS_BLOCKARG
                argc_extra = 1
        # Not ARGS_SIMPLE: CRuby clears it whenever a block ISeq is attached.
        simple = (not operand.has_kwarg
                  and (flags & ~optable.SIMPLE_CALL_FLAGS) == 0)
        kw_names = []
        kw_splat = (flags & optable.CALL_FLAG_KW_SPLAT) != 0
        splat = (flags & optable.CALL_FLAG_ARGS_SPLAT) != 0
        blockarg = (flags & optable.CALL_FLAG_ARGS_BLOCKARG) != 0
        if not simple:
            # Refused here, not at the send: the ISeq could not finish running.
            if (len(operand.kw_names) == 0 and not kw_splat and not splat) or \
                    (len(operand.kw_names) > 0 and kw_splat) or \
                    (flags & ~optable.SPLAT_CALL_FLAGS) != 0:
                raise UnsupportedOperation(
                    "the call to '%s' passes %s, which RPyYARV does not "
                    "support" % (operand.strval, self.call_flag_name(operand)))
            for name in operand.kw_names:
                kw_names.append(symbols.intern(name))
        # iseq.c:3537 reports orig_argc without them; a **splat Hash counts.
        return W_CallInfo(symbols.intern(operand.strval),
                          operand.intval + len(kw_names) + argc_extra,
                          simple, (flags & optable.CALL_FLAG_FCALL) != 0,
                          (flags & optable.CALL_FLAG_SUPER) != 0, blockarg,
                          [m for m in kw_names], kw_splat, splat)

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
    """No CRuby to fall back to here, so it refuses what it cannot load."""
    return load_strict(iseqdump.parse(text))
