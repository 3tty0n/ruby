"""RPYYARV_DEBUG names the channels to turn on, comma separated."""

import os

from rpyyarv import boot
from rpyyarv import insns
from rpyyarv import optable
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.iseq import NO_BLOCK_ISEQ
from rpyyarv.rlib import dont_look_inside, oswrite, rpython_heap_bytes

INSN = 1
STACK = 2
CALL = 4
ISEQ = 8
SUMMARY = 16
LOAD = 32
ALL = INSN | STACK | CALL | ISEQ | SUMMARY | LOAD

_NAMES = ['insn', 'stack', 'call', 'iseq', 'summary', 'load']
_BITS = [INSN, STACK, CALL, ISEQ, SUMMARY, LOAD]
CHANNELS = 'insn, stack, call, iseq, summary, load, all'


class _State(object):
    # Quasi-immutable: written at startup only, read per insn and per send.
    _immutable_fields_ = ['enabled?']

    def __init__(self):
        # Kept apart from `channels`: the dispatch loop reads it per insn.
        self.enabled = False
        self.channels = 0
        self.depth = 0
        self.counts = [0] * insns.INSTRUCTION_COUNT


state = _State()


class _Coverage(object):
    # Quasi-immutable, so the count folds away when it is off.
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
        self.delegated = []     # 'path: why RPyYARV would not run it'
        self.by_name = {}       # method name -> foreign sends of it
        self.by_site = {}       # (mid, receiver class, arg class) -> the same
        self.by_inval = {}      # (klass, rid) -> method-cache flushes it caused


coverage = _Coverage()


def count_native():
    if coverage.enabled:
        coverage.native += 1


@dont_look_inside
def count_foreign(mid):
    # The mid, not its name: resolving costs a lookup per foreign send.
    if coverage.enabled:
        coverage.foreign += 1
        name = symbols.name_of(mid)
        coverage.by_name[name] = coverage.by_name.get(name, 0) + 1


@dont_look_inside
def count_foreign_site(mid, recv, arg):
    """count_foreign, plus receiver and argument classes, named at report."""
    if coverage.enabled:
        count_foreign(mid)
        key = (mid, value.class_of(recv),
               0 if arg == value.Q_UNDEF else value.class_of(arg))
        coverage.by_site[key] = coverage.by_site.get(key, 0) + 1


@dont_look_inside
def count_invalidation(klass, rid):
    """Who keeps flushing the method cache; named at report, not here."""
    if coverage.enabled:
        key = (klass, rid)
        coverage.by_inval[key] = coverage.by_inval.get(key, 0) + 1


def configure_coverage():
    if os.environ.get('RPYYARV_COVERAGE') == '1':
        coverage.enabled = True


def record_file(path, total, supported, reason):
    """One .rb file's outcome; a non-empty reason means CRuby ran it."""
    if not coverage.enabled:
        return
    coverage.iseqs_total += total
    coverage.iseqs_native += supported
    if reason == '':
        coverage.files_native += 1
    else:
        coverage.files_cruby += 1
        coverage.delegated.append('%s: %s' % (path, reason))


def report():
    """What actually ran: an iseq figure alone reads as 100%."""
    if not coverage.enabled:
        return
    note('sends: rpyyarv %d, cruby %d' % (coverage.native, coverage.foreign))
    from rpyyarv import dispatch
    from rpyyarv import gcroots
    note('method-cache invalidations: %d (skipped %d)'
         % (dispatch.owners.invalidations, dispatch.owners.skipped))
    note('gc roots: %s' % gcroots.root_inventory())
    note('root marking: %d walk(s), %d ns' % (gcroots.mark_cost.walks,
                                              gcroots.mark_cost.ns))
    note('heap footprint: rpython %d bytes' % rpython_heap_bytes())
    note('files: rpyyarv %d, delegated to cruby %d'
         % (coverage.files_native, coverage.files_cruby))
    percent = (100 * coverage.iseqs_native // coverage.iseqs_total
               if coverage.iseqs_total > 0 else 0)
    note('iseqs: %d/%d (%d%%) across %d file(s)'
         % (coverage.iseqs_native, coverage.iseqs_total, percent,
            coverage.files_native + coverage.files_cruby))
    for i in range(len(coverage.delegated)):
        note('  delegated to cruby: %s' % coverage.delegated[i])
    for name, n in _top_foreign():
        note('  cruby send: %s %d' % (name, n))
    for key, n in _top_sites():
        note('  cruby site: %s(%s, %s) %d'
             % (symbols.name_of(key[0]), _class_name(key[1]),
                _class_name(key[2]), n))
    for key, n in _top_invalidations():
        note('  invalidated by: %s#%s %d'
             % (_class_name(key[0]), _rid_name(key[1]), n))


def _rid_name(rid):
    if rid == 0:
        return '(chain move)'
    return boot.id_name(rid)


def _top_invalidations():
    counts = []
    keys = []
    for key, n in coverage.by_inval.items():
        at = len(counts)
        while at > 0 and counts[at - 1] < n:
            at -= 1
        assert at >= 0
        counts.insert(at, n)
        keys.insert(at, key)
    out = []
    for i in range(len(keys)):
        if i == 25:
            break
        out.append((keys[i], counts[i]))
    return out


def _class_name(klass):
    if klass == 0:
        return '-'
    return boot.inspect(klass)


def _top_sites():
    counts = []
    keys = []
    for key, n in coverage.by_site.items():
        at = len(counts)
        while at > 0 and counts[at - 1] < n:
            at -= 1
        assert at >= 0
        counts.insert(at, n)
        keys.insert(at, key)
    out = []
    for i in range(len(counts)):
        if i == 25:
            break
        out.append((keys[i], counts[i]))
    return out


def _top_foreign():
    """The 20 method names most often sent out to CRuby, most frequent first."""
    counts = []
    names = []
    for name, n in coverage.by_name.items():
        at = len(counts)
        while at > 0 and counts[at - 1] < n:
            at -= 1
        assert at >= 0
        counts.insert(at, n)
        names.insert(at, name)
    out = []
    for i in range(len(counts)):
        if i == 20:
            break
        out.append((names[i], counts[i]))
    return out


def write(s):
    oswrite(2, s)


def note(msg):
    """Unconditional one-liner, for a print dropped in while hunting a bug."""
    write('[rpyyarv] %s\n' % msg)


class _Loads(object):
    def __init__(self):
        self.n = 0


loads = _Loads()


def note_load(path, kind):
    """One line per file the require path touched, to watch load progress.
    A `start` with no `done` after it names the file the load is stuck in."""
    if state.channels & LOAD == 0:
        return
    loads.n += 1
    note('load #%d %s %s' % (loads.n, kind, path))


def note_invalidation(n):
    """One line per invalidation; timing tells load noise from a killer."""
    if coverage.enabled:
        note('invalidation #%d' % n)


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
        parts.append(value.repr_of(frame.slots[i]))
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
