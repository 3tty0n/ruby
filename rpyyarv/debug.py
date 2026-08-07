"""Tracing hooks for watching the interpreter run.

RPYYARV_DEBUG names the channels to turn on, comma separated:

    insn     one line per dispatched instruction
    stack    the operand stack alongside it
    call     method enter and leave, with arguments and return value
    iseq     disassemble the loaded code before running it
    summary  how many times each instruction ran, at exit
    all      every channel above

"""

import os

import insns
import optable
import symbols
import value
from iseq import NO_BLOCK_ISEQ
from rlib import dont_look_inside, oswrite

INSN = 1
STACK = 2
CALL = 4
ISEQ = 8
SUMMARY = 16
ALL = INSN | STACK | CALL | ISEQ | SUMMARY

_NAMES = ['insn', 'stack', 'call', 'iseq', 'summary']
_BITS = [INSN, STACK, CALL, ISEQ, SUMMARY]
CHANNELS = 'insn, stack, call, iseq, summary, all'


class _State(object):
    def __init__(self):
        # Kept apart from `channels`: the dispatch loop reads it per insn.
        self.enabled = False
        self.channels = 0
        self.depth = 0
        self.counts = [0] * insns.INSTRUCTION_COUNT


state = _State()


class _Coverage(object):
    # Quasi-immutable, so the count in the send path folds away when it is
    # off; see rubycall._Stress.
    _immutable_fields_ = ['enabled?']

    def __init__(self):
        self.enabled = False
        self.native = 0         # sends RPyYARV ran itself
        self.foreign = 0        # sends that went out through rb_funcallv
        # Every .rb file the program pulled in, main script included.
        self.files_native = 0
        self.files_cruby = 0
        self.iseqs_total = 0
        self.iseqs_native = 0
        self.punted = []        # 'path: why RPyYARV would not run it'


coverage = _Coverage()


def count_native():
    if coverage.enabled:
        coverage.native += 1


@dont_look_inside
def count_foreign():
    if coverage.enabled:
        coverage.foreign += 1


def configure_coverage():
    if os.environ.get('RPYYARV_COVERAGE') == '1':
        coverage.enabled = True


def record_file(path, total, supported, reason):
    """One .rb file's outcome. A non-empty reason means RPyYARV punted it to
    CRuby, whose method definitions its own dispatch never sees."""
    if not coverage.enabled:
        return
    coverage.iseqs_total += total
    coverage.iseqs_native += supported
    if reason == '':
        coverage.files_native += 1
    else:
        coverage.files_cruby += 1
        coverage.punted.append('%s: %s' % (path, reason))


def report():
    """What actually ran, not what could have: an iseq figure alone reads as
    100% while every send goes out to CRuby."""
    if not coverage.enabled:
        return
    note('sends: rpyyarv %d, cruby %d' % (coverage.native, coverage.foreign))
    note('files: rpyyarv %d, punted to cruby %d'
         % (coverage.files_native, coverage.files_cruby))
    percent = (100 * coverage.iseqs_native // coverage.iseqs_total
               if coverage.iseqs_total > 0 else 0)
    note('iseqs: %d/%d (%d%%) across %d file(s)'
         % (coverage.iseqs_native, coverage.iseqs_total, percent,
            coverage.files_native + coverage.files_cruby))
    for i in range(len(coverage.punted)):
        note('  punted to cruby: %s' % coverage.punted[i])


def write(s):
    oswrite(2, s)


def note(msg):
    """Unconditional one-liner, for a print dropped in while hunting a bug."""
    write('[rpyyarv] %s\n' % msg)


def on(channel):
    return state.channels & channel != 0


def configure(spec):
    """Turn on the named channels; returns the names it did not recognise."""
    unknown = []
    for raw in spec.split(','):
        name = raw.strip()
        if name == '':
            continue
        if name == 'all':
            state.channels |= ALL
            continue
        bit = 0
        for i in range(len(_NAMES)):
            if _NAMES[i] == name:
                bit = _BITS[i]
                break
        if bit == 0:
            unknown.append(name)
        else:
            state.channels |= bit
    state.enabled = state.channels != 0
    return unknown


def configure_from_env():
    spec = os.environ.get('RPYYARV_DEBUG')
    if spec is None:
        return []
    return configure(spec)


def reset():
    state.channels = 0
    state.enabled = False
    state.depth = 0
    for i in range(len(state.counts)):
        state.counts[i] = 0


@dont_look_inside
def trace_insn(w_iseq, pc, frame):
    state.counts[w_iseq.code[pc]] += 1
    if state.channels & INSN:
        write('%s%s  %s\n' % (_indent(), _pad(str(pc), 4),
                              insn_at(w_iseq, pc)))
    if state.channels & STACK:
        write('%s      stack %s\n' % (_indent(), _stack_repr(frame)))


@dont_look_inside
def trace_enter(mid, args):
    if state.channels & CALL:
        write('%s-> %s(%s)\n' % (_indent(), symbols.name_of(mid),
                                 _list_repr(args)))
    state.depth += 1


@dont_look_inside
def trace_leave(mid, ret):
    if state.depth > 0:
        state.depth -= 1
    if state.channels & CALL:
        write('%s<- %s = %s\n' % (_indent(), symbols.name_of(mid),
                                  value.repr_of(ret)))


def dump_iseq(w_iseq):
    if state.channels & ISEQ:
        write(disasm(w_iseq))


def summary():
    if not state.channels & SUMMARY:
        return
    counts, names = _ranked()
    total = 0
    for i in range(len(counts)):
        total += counts[i]
    lines = ['== %d instruction(s) executed\n' % total]
    for i in range(len(counts)):
        lines.append('%s  %s\n' % (_pad(str(counts[i]), 10), names[i]))
    write(''.join(lines))


def disasm(w_iseq):
    """The loaded code as text, operands decoded back through optable."""
    lines = []
    _disasm_into(w_iseq, lines)
    return ''.join(lines)


def insn_at(w_iseq, pc):
    code = w_iseq.code
    op = code[pc]
    positions = optable.EMIT_POSITIONS[op]
    if len(positions) == 0:
        return insns.NAMES[op]
    parts = []
    for i in range(len(positions)):
        parts.append(_operand(w_iseq, op, positions[i], code[pc + 1 + i]))
    return '%s %s' % (insns.NAMES[op], ', '.join(parts))


def _disasm_into(w_iseq, lines):
    lines.append('== %s (%d local(s), stack %d, %d param(s))\n'
                 % (w_iseq.name, w_iseq.nlocals, w_iseq.stack_max,
                    w_iseq.nparams))
    code = w_iseq.code
    pc = 0
    while pc < len(code):
        lines.append('%s  %s\n' % (_pad(str(pc), 4), insn_at(w_iseq, pc)))
        pc += 1 + optable.NUM_OPERANDS[code[pc]]
    for w_nested in w_iseq.iseqs:
        _disasm_into(w_nested, lines)


def _operand(w_iseq, op, pos, val):
    t = insns.OPERAND_TYPES[op][pos]
    if t == insns.T_VALUE:
        return value.repr_of(w_iseq.consts[val])
    if t == insns.T_CALL_DATA:
        return w_iseq.callinfos[val].repr()
    if t == insns.T_ISEQ:
        if val == NO_BLOCK_ISEQ:
            return 'no block'
        return w_iseq.iseqs[val].repr()
    if t == insns.T_ID or t == insns.T_IC:
        return symbols.name_of(val)
    if t == insns.T_LINDEX_T:
        slot = val & optable.LOCAL_SLOT_MASK
        level = val >> optable.LOCAL_LEVEL_SHIFT
        if level == 0:
            return 'local[%d]' % slot
        return 'local[%d]^%d' % (slot, level)
    if t == insns.T_OFFSET:
        return '-> %d' % val
    return str(val)


def _stack_repr(frame):
    parts = []
    for i in range(frame.sp):
        parts.append(value.repr_of(frame.stack[i]))
    return '[%s]' % ', '.join(parts)


def _list_repr(args):
    parts = []
    for i in range(len(args)):
        parts.append(value.repr_of(args[i]))
    return ', '.join(parts)


def _ranked():
    """Executed instructions, most frequent first."""
    counts = []
    names = []
    for op in range(len(state.counts)):
        n = state.counts[op]
        if n == 0:
            continue
        at = len(counts)
        while at > 0 and counts[at - 1] < n:
            at -= 1
        assert at >= 0                  # RPython proof for insert()
        counts.insert(at, n)
        names.insert(at, insns.NAMES[op])
    return counts, names


def _indent():
    parts = []
    for i in range(state.depth):
        parts.append('  ')
    return ''.join(parts)


def _pad(s, width):
    while len(s) < width:
        s = ' ' + s
    return s
