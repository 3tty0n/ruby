"""Helpers for writing unit tests."""

import os
import shutil
import subprocess
import tempfile

from rpyyarv import debug
from rpyyarv import insns
from rpyyarv import interp
from rpyyarv import kernel
from rpyyarv import loader
from rpyyarv import optable
from rpyyarv import rawiseq
from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.frame import Frame
from rpyyarv.iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.float import W_Float
from rpyyarv.objects.main import W_Main
from rpyyarv.objects.regexp import W_Regexp
from rpyyarv.objects.string import W_String
from rpyyarv.objects.symbol import W_Symbol
from rpyyarv.objects.transparent import W_Fixnum, w_false, w_nil, w_true

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get('RPYYARV_BUILD',
                       os.path.join(os.path.dirname(ROOT), 'build'))
DUMPER = os.path.join(ROOT, 'scripts', 'dump_iseq.rb')


def ruby_exe():
    """This tree's ruby as (exe, env); only it matches insns.py.

    Returns (None, why) when it is missing or will not run, so a caller can
    skip rather than fail.
    """
    exe = os.environ.get('RUBY', os.path.join(BUILD, 'ruby'))
    if not os.path.exists(exe):
        return None, 'no ruby in %s; build CRuby first' % BUILD
    env = dict(os.environ)
    # The build tree's libruby is tagged with its install prefix, not its path
    for var in ('DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
        env[var] = os.pathsep.join([BUILD] + [p for p in [env.get(var)] if p])
    try:
        subprocess.check_output([exe, '-e', ''], env=env,
                                stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as e:
        return None, '%s will not run: %s' % (exe, e)
    return exe, env


def _write_program(source):
    tmp = tempfile.mkdtemp(prefix='rpyyarv-')
    path = os.path.join(tmp, 'program.rb')
    f = open(path, 'w')
    try:
        f.write(source)
    finally:
        f.close()
    return tmp, path


def compile_rb(path, ruby=None):
    """Compiles a .rb to the ISeq dump text load_dump() reads."""
    exe, env = ruby if ruby else ruby_exe()
    text = subprocess.check_output([exe, DUMPER, path], env=env)
    if not isinstance(text, str):
        text = text.decode('latin-1')
    return text


def _ruby_stdout(path, ruby):
    exe, env = ruby if ruby else ruby_exe()
    if exe is None:
        raise AssertionError(env)
    try:
        out = subprocess.check_output([exe, path], env=env,
                                      stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        detail = e.output
        if not isinstance(detail, str):
            detail = detail.decode('latin-1')
        raise AssertionError('CRuby failed on %s:\n%s' % (path, detail))
    if not isinstance(out, str):
        out = out.decode('latin-1')
    return out


def run_ruby(source, ruby=None):
    """Runs source on CRuby and returns its stdout, for differential tests."""
    tmp, path = _write_program(source)
    try:
        return _ruby_stdout(path, ruby)
    finally:
        shutil.rmtree(tmp)


def run_ruby_file(path, ruby=None):
    """Runs an existing .rb on CRuby and returns its stdout."""
    return _ruby_stdout(path, ruby)


def asm(consts, nlocals, stack_max, items, name='<test>', nparams=0,
        simple_params=True):
    """Tiny assembler. In items, ':name' defines a label and takes no space;
    any other string references one and occupies a slot."""
    labels = {}
    pos = 0
    for item in items:
        if isinstance(item, str) and item.startswith(':'):
            labels[item[1:]] = pos
        else:
            pos += 1
    code = []
    for item in items:
        if isinstance(item, str):
            if item.startswith(':'):
                continue
            code.append(labels[item])
        else:
            code.append(item)
    return W_ISeq(name, code, consts, nlocals, stack_max, nparams,
                  simple_params)


def compile_source(source, ruby=None):
    """Compiles Ruby source text to an ISeq dump, through a temp file."""
    tmp, path = _write_program(source)
    try:
        return compile_rb(path, ruby)
    finally:
        shutil.rmtree(tmp)


def decode(w_iseq):
    """The loaded code as (pc, opcode, operands) tuples."""
    code = w_iseq.code
    out = []
    pc = 0
    while pc < len(code):
        op = code[pc]
        width = optable.NUM_OPERANDS[op]
        out.append((pc, op, code[pc + 1:pc + 1 + width]))
        pc += 1 + width
    return out


def only_insn(w_iseq, op):
    """The one decoded instruction with opcode op, as (opcode, operands)."""
    hits = []
    for _, got, operands in decode(w_iseq):
        if got == op:
            hits.append((got, operands))
    assert len(hits) == 1, 'expected one %s, found %d' % (
        insns.NAMES[op], len(hits))
    return hits[0]


def defined_method(w_iseq, name):
    """The W_ISeq body a `def name` in w_iseq compiles to."""
    for _, op, operands in decode(w_iseq):
        if op == insns.DEFINEMETHOD:
            mid, body_index = operands
            if symbols.name_of(mid) == name:
                return w_iseq.consts[body_index]
    raise AssertionError('no method %r in %r' % (name, w_iseq.name))


def run(w_iseq, w_self=None):
    """Runs on a self of its own, so tests cannot see each other."""
    if w_self is None:
        w_self = W_Main()
    return interp.execute(w_iseq, Frame(w_iseq, w_self))


def run_dump(text, w_self=None):
    """Loads an ISeq dump -- see the `compile_rb` fixture -- and runs it."""
    return run(loader.load_dump(text), w_self)


def expect_unsupported(w_iseq, w_self, msg):
    try:
        run(w_iseq, w_self)
    except UnsupportedOperation as e:
        assert e.msg == msg, 'got %r, expected %r' % (e.msg, msg)
    else:
        raise AssertionError('expected UnsupportedOperation: %s' % msg)


def capture(func):
    """Collect what the builtins print instead of writing to stdout."""
    out = []
    saved = kernel.write
    kernel.write = lambda s: out.append(s)
    try:
        w_ret = func()
    finally:
        kernel.write = saved
    return ''.join(out), w_ret


def traced(channels, thunk):
    """Runs thunk with the debug channels on, returning what debug wrote."""
    out = []
    saved_puts = kernel.write
    debug.reset()
    debug.configure(channels)
    debug.write = out.append
    kernel.write = lambda s: None
    try:
        thunk()
    finally:
        kernel.write = saved_puts
        debug.reset()
    return ''.join(out)


def fixture(name):
    """Reads a recorded file from test/, e.g. fixture('fib.iseq')."""
    f = open(os.path.join(HERE, name))
    try:
        return f.read()
    finally:
        f.close()


def _base_opcode(insn):
    if insn.name in insns.SPEC_BASE:
        return insns.SPEC_BASE[insn.name]
    return insns.NAME_TO_OP[insn.name]


def _raw_operands(insn, op):
    """The dump's operands with specialized variants filled back in."""
    want = len(insns.OPERAND_TYPES[op])
    given = insn.operands
    fill = insns.SPEC_FILL.get(insn.name)
    if fill is None:
        assert len(given) == want
        return given
    operands = []
    taken = 0
    for pos in range(want):
        value = None
        for pair in fill:
            if pair[0] == pos:
                value = rawiseq.int_operand(pair[1])
        if value is None:
            value = given[taken]
            taken += 1
        operands.append(value)
    assert taken == len(given)
    return operands


def _check_code_references(w_iseq):
    starts = []
    decoded = decode(w_iseq)
    for pc, _, _ in decoded:
        starts.append(pc)
    starts.append(len(w_iseq.code))
    for _, op, operands in decoded:
        assert optable.IMPLEMENTED[op]
        positions = optable.EMIT_POSITIONS[op]
        assert len(operands) == len(positions)
        for i, value in enumerate(operands):
            t = insns.OPERAND_TYPES[op][positions[i]]
            if t == insns.T_OFFSET:
                assert value in starts, (
                    '%s in %s jumps outside the code'
                    % (insns.NAMES[op], w_iseq.name))
            elif t == insns.T_LINDEX_T:
                assert 0 <= value < w_iseq.nlocals
            elif t == insns.T_ISEQ:
                if value == NO_BLOCK_ISEQ:
                    assert op == insns.SEND
                else:
                    assert 0 <= value < len(w_iseq.consts)
                    assert isinstance(w_iseq.consts[value], W_ISeq)
            elif t == insns.T_CALL_DATA:
                assert 0 <= value < len(w_iseq.consts)
                assert isinstance(w_iseq.consts[value], W_CallInfo)
            elif t == insns.T_VALUE:
                assert 0 <= value < len(w_iseq.consts)
            elif t == insns.T_ID or t == insns.T_RB_NUM_T:
                pass
            else:
                raise AssertionError('unexpected operand type %r' % t)


def _check_literal(w_x, raw_op):
    kind = raw_op.kind
    if kind == rawiseq.OP_INT:
        assert isinstance(w_x, W_Fixnum)
        assert w_x.int_w() == raw_op.intval
    elif kind == rawiseq.OP_FLOAT:
        assert isinstance(w_x, W_Float)
        assert repr(w_x.float_w()) == repr(raw_op.floatval)    # tells -0.0 apart
    elif kind == rawiseq.OP_NIL:
        assert w_x is w_nil
    elif kind == rawiseq.OP_TRUE:
        assert w_x is w_true
    elif kind == rawiseq.OP_FALSE:
        assert w_x is w_false
    elif kind == rawiseq.OP_STR:
        assert isinstance(w_x, W_String)
        assert w_x.str_w() == raw_op.strval
    elif kind == rawiseq.OP_SYM:
        assert isinstance(w_x, W_Symbol)
        assert symbols.name_of(w_x.mid) == raw_op.strval
    elif kind == rawiseq.OP_ARRAY:
        assert isinstance(w_x, W_Array)
        assert len(w_x.items_w) == len(raw_op.items)
        for i in range(len(raw_op.items)):
            _check_literal(w_x.items_w[i], raw_op.items[i])
    elif kind == rawiseq.OP_OTHER:
        # The pattern itself is checked by the regexp tests.
        assert isinstance(w_x, W_Regexp)
    else:
        raise AssertionError('unexpected literal kind %r' % kind)


def _check_operand_values(raw, w_iseq, decoded, labels, l):
    for (_, op, operands), insn in zip(decoded, raw.insns):
        raw_ops = _raw_operands(insn, op)
        for i, pos in enumerate(optable.EMIT_POSITIONS[op]):
            t = insns.OPERAND_TYPES[op][pos]
            got = operands[i]
            raw_op = raw_ops[pos]
            if t == insns.T_OFFSET:
                assert raw_op.kind == rawiseq.OP_SYM
                assert got == labels[raw_op.strval]
            elif t == insns.T_LINDEX_T:
                assert raw_op.kind == rawiseq.OP_INT
                assert got == (raw.nlocals - raw_op.intval
                               + optable.ENV_DATA_SIZE - 1)
            elif t == insns.T_RB_NUM_T:
                assert raw_op.kind == rawiseq.OP_INT
                assert got == raw_op.intval
            elif t == insns.T_ID:
                assert raw_op.kind == rawiseq.OP_SYM
                assert symbols.name_of(got) == raw_op.strval
            elif t == insns.T_ISEQ:
                if raw_op.kind == rawiseq.OP_NIL:
                    assert got == NO_BLOCK_ISEQ
                else:
                    assert raw_op.kind == rawiseq.OP_ISEQ
                    assert w_iseq.consts[got] is l.w_iseqs[raw_op.intval]
            elif t == insns.T_CALL_DATA:
                assert raw_op.kind == rawiseq.OP_CALL
                w_ci = w_iseq.consts[got]
                assert w_ci.mid == symbols.intern(raw_op.strval)
                assert w_ci.argc == raw_op.intval
                assert w_ci.fcall == (
                    (raw_op.flag & optable.CALL_FLAG_FCALL) != 0)
                has_block = (op == insns.SEND
                             and raw_ops[1].kind == rawiseq.OP_ISEQ)
                simple = (not raw_op.has_kwarg
                          and (raw_op.flag & ~optable.SIMPLE_CALL_FLAGS) == 0
                          and ((raw_op.flag & optable.CALL_FLAG_ARGS_SIMPLE)
                               != 0 or has_block))
                assert w_ci.simple == simple
            elif t == insns.T_VALUE:
                assert 0 <= got < len(w_iseq.consts)
                _check_literal(w_iseq.consts[got], raw_op)
            else:
                raise AssertionError('unexpected operand type %r' % t)


def check_loaded(program, l):
    assert set(l.w_iseqs) <= set(range(len(program.iseqs)))
    for index, raw in enumerate(program.iseqs):
        if index not in l.w_iseqs:
            continue
        w_iseq = l.w_iseqs[index]
        assert w_iseq.name == raw.name
        assert w_iseq.nlocals == raw.nlocals
        assert w_iseq.stack_max == raw.stack_max
        assert w_iseq.nparams == raw.lead_num
        if raw.type == 'block' and raw.lead_num == 1:
            assert w_iseq.simple_params == (
                raw.extra_params == 'ambiguous_param0')
        else:
            assert w_iseq.simple_params == (raw.extra_params == '')
        decoded = decode(w_iseq)
        assert len(decoded) == len(raw.insns)
        starts = []
        labels = {}
        pc = 0
        for insn in raw.insns:
            base = _base_opcode(insn)
            starts.append(pc)
            pc += 1 + optable.NUM_OPERANDS[base]
        starts.append(pc)
        for name, at in raw.labels.items():
            labels[name] = starts[at]
        for (_, op, _), insn in zip(decoded, raw.insns):
            assert op == _base_opcode(insn)
        assert len(w_iseq.code) == pc
        _check_code_references(w_iseq)
        _check_operand_values(raw, w_iseq, decoded, labels, l)
