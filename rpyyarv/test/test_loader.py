import os

import pytest

import insns
import iseqdump
import loader
import optable
import rawiseq
import symbols
from error import LoadError, UnsupportedOperation
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from objects.array import W_Array
from objects.string import W_String
from objects.regexp import W_Regexp
from objects.transparent import W_Fixnum, w_false, w_nil, w_true
from support import (HERE, decode, defined_method, fixture, only_insn, run,
                     run_dump, run_ruby_file)

def expect(exc_class, text, msg):
    try:
        loader.load_dump(text)
    except exc_class as e:
        assert e.msg == msg, 'got %r, expected %r' % (e.msg, msg)
    except Exception as e:
        raise AssertionError('expected %s(%r), got %r'
                             % (exc_class.__name__, msg, e))
    else:
        raise AssertionError('expected %s: %s' % (exc_class.__name__, msg))


def patched(text, old, new):
    assert old in text, 'fixture no longer contains %r' % old
    return text.replace(old, new, 1)


def test_fib_rec_end_to_end():
    assert run_dump(fixture('fib_rec.iseq')).int_w() == 6765


def test_fib_rec_from_source(compile_rb):
    """.rb in, value out, straight through this tree's compiler."""
    assert run_dump(compile_rb(os.path.join(HERE, 'fib_rec.rb'))).int_w() \
        == 6765


def test_fib_iterative_end_to_end(out):
    # test/fib.rb, the interception fixture: interpolation, puts and all
    w_ret = run_dump(fixture('fib.iseq'))
    assert out.text == 'EXECUTED:832040\n'
    assert w_ret is w_nil


def test_string_literal_loaded():
    w_iseq = loader.load_dump(fixture('fib.iseq'))
    strings = [w.str_w() for w in w_iseq.consts if isinstance(w, W_String)]
    assert strings == ['EXECUTED:']


def _regexp_const(compile_source, source):
    """Returns the W_Regexp the loader produced for a regexp source."""
    w_iseq = loader.load_dump(compile_source(source))
    regexps = [w for w in w_iseq.consts if isinstance(w, W_Regexp)]
    assert len(regexps) == 1
    return regexps[0]


def test_regexp_literal_loaded(compile_source):
    assert _regexp_const(compile_source, '/foo/').pattern == 'foo'
    # `//` is the empty pattern, not a fall-through to "no such object yet".
    assert _regexp_const(compile_source, '//').pattern == ''


def test_regexp_literal_with_flags_is_rejected(compile_source):
    expect(UnsupportedOperation, compile_source('/foo/i'),
           "regexp literal /foo/i in '<main>' is not supported yet")
    expect(UnsupportedOperation, compile_source('/foo/mix'),
           "regexp literal /foo/mix in '<main>' is not supported yet")


def test_regexp_literal_unescapes_the_delimiter(compile_source):
    # The dump writes a backslash as \\, so the loader sees the inspect
    # form /a\/b/; its pattern is a/b, as Regexp#source would report.
    # (inspect cannot distinguish source "a/b" from "a\/b"; both match '/'.)
    assert _regexp_const(compile_source, '/a\\/b/').pattern == 'a/b'


def _fib_body():
    return defined_method(loader.load_dump(fixture('fib_rec.iseq')), 'fib')


def test_locals_end_to_end():
    # f(9, 4)
    assert run(loader.load_dump(fixture('locals.iseq'))).int_w() == 5


def test_local_slots_are_remapped():
    # The dump's lindex_t operands count down from the top of the
    # environment; the loader turns them into frame slots.
    w_body = defined_method(loader.load_dump(fixture('locals.iseq')), 'f')
    assert w_body.nlocals == 3
    assert w_body.nparams == 2
    assert [(op, operands) for _, op, operands in decode(w_body)] == [
        (insns.GETLOCAL, [0]),
        (insns.GETLOCAL, [1]),
        (insns.OPT_MINUS, []),
        (insns.SETLOCAL, [2]),
        (insns.GETLOCAL, [2]),
        (insns.LEAVE, []),
    ]


def test_nested_iseq():
    w_body = _fib_body()
    assert isinstance(w_body, W_ISeq)
    assert w_body.name == 'fib'
    assert w_body.nparams == 1
    assert w_body.simple_params
    calls = [w for w in w_body.consts if isinstance(w, W_CallInfo)]
    assert calls
    assert all(w_ci.simple for w_ci in calls)
    assert {w_ci.argc for w_ci in calls} == {1}


def test_specialized_variants_lower_to_putobject():
    w_body = _fib_body()
    puts = [operands[0] for _, op, operands in decode(w_body)
            if op == insns.PUTOBJECT]
    # putobject 2, putobject_INT2FIX_1_, putobject 2
    assert [w_body.consts[i].int_w() for i in puts] == [2, 1, 2]


def test_equal_fixnum_literals_share_a_pool_slot():
    w_body = _fib_body()
    puts = [operands[0] for _, op, operands in decode(w_body)
            if op == insns.PUTOBJECT]
    assert puts[0] == puts[2]
    assert puts[1] != puts[0]


def test_missing_instructions_are_reported_together():
    text = patched(fixture('fib_rec.iseq'), 'insn\tputself\ninsn\tputobject',
                   'insn\tputstring\ts:x\ninsn\tnewhash\ti:0\n'
                   'insn\tputstring\ts:y\n'
                   'insn\tputself\ninsn\tputobject')
    l = loader.Loader(iseqdump.parse(text))
    l.scan()
    assert l.missing == {'putstring': 2, 'newhash': 1}
    assert l.missing_names == ['putstring', 'newhash']
    expect(UnsupportedOperation, text,
           '2 unimplemented instruction(s) in 3 occurrence(s): '
           'putstring x2, newhash x1')


def test_missing_instructions_are_counted():
    text = patched(fixture('fib_rec.iseq'),
                   'insn\tputself\ninsn\tgetlocal_WC_0\ti:3',
                   'insn\tnewarray\ti:0\ninsn\tnewarray\ti:0\n'
                   'insn\tputstring\ts:x\n'
                   'insn\tputself\ninsn\tgetlocal_WC_0\ti:3')
    expect(UnsupportedOperation, text,
           '2 unimplemented instruction(s) in 3 occurrence(s): '
           'newarray x2, putstring x1')


def test_local_level_rejected():
    expect(UnsupportedOperation, fixture('block.iseq'),
           "getlocal at level 1 in 'block in <main>' reaches an enclosing "
           "scope, which RPyYARV does not support")


def test_blockless_send_encoding():
    # the same call site with its blockiseq dropped
    text = patched(fixture('block.iseq'),
                   'insn\tsend\tc:0,0,0,times\tq:1',
                   'insn\tsend\tc:0,0,0,times\tn:')
    w_iseq = loader.load_dump(text)
    _, operands = only_insn(w_iseq, insns.SEND)
    assert operands[1] == NO_BLOCK_ISEQ
    w_ci = w_iseq.consts[operands[0]]
    assert isinstance(w_ci, W_CallInfo)
    assert not w_ci.simple


def test_a_call_with_a_block_literal_is_simple():
    # CRuby leaves ARGS_SIMPLE off a call site that has a block literal
    text = patched(fixture('block.iseq'), 'insn\tgetlocal_WC_1\ti:3',
                   'insn\tputnil')
    w_iseq = loader.load_dump(text)
    _, operands = only_insn(w_iseq, insns.SEND)
    w_ci = w_iseq.consts[operands[0]]
    assert isinstance(w_ci, W_CallInfo)
    assert w_ci.simple
    assert operands[1] != NO_BLOCK_ISEQ
    assert isinstance(w_iseq.consts[operands[1]], W_ISeq)


def test_trace_build_rejected():
    text = patched(fixture('fib_rec.iseq'), 'insn\tputself',
                   'insn\ttrace_putself')
    expect(UnsupportedOperation, text,
           "instruction 'trace_putself' in '<main>' comes from a "
           "TracePoint-enabled build, which RPyYARV does not support")


def test_instruction_from_another_ruby():
    text = patched(fixture('fib_rec.iseq'), 'insn\tputself',
                   'insn\topt_getinlinecache')
    expect(LoadError, text,
           "'opt_getinlinecache' in '<main>' is not an instruction in "
           "insns.def; the input and insns.py come from different rubies")


def test_operand_shape_is_checked():
    text = patched(fixture('fib_rec.iseq'), 'insn\tputobject\ti:20',
                   'insn\tputobject')
    expect(LoadError, text,
           "'putobject' in '<main>' has 0 operand(s), insns.def says 1")

    text = patched(fixture('fib_rec.iseq'), 'insn\tbranchunless\ty:label_11',
                   'insn\tbranchunless\ty:nowhere')
    expect(LoadError, text,
           "branchunless in 'fib' jumps to unknown label nowhere")


def test_unsupported_literal():
    text = patched(fixture('fib_rec.iseq'), 'insn\tputobject\ti:20',
                   'insn\tputobject\ty:a_symbol')
    expect(UnsupportedOperation, text,
           "putobject of Symbol a_symbol in '<main>': RPyYARV has no such "
           "object yet")


def test_malformed_dump():
    expect(LoadError, 'dump\t99\t3.3.8\tx.rb\n',
           'dump format version 99, expected 1')
    expect(LoadError, 'iseq\t0\ttop\t<main>\n', 'line 1: no dump header')
    expect(LoadError, 'dump\t1\t3.3.8\tx.rb\n', 'dump contains no iseq')
    text = patched(fixture('fib_rec.iseq'), 'insn\tputself',
                   'insn\tputself\ti')
    expect(LoadError, text, 'malformed operand: i')


CRUBY_CASES = [
    ('arith', 'puts 1 + 2\n'),
    ('precedence', 'puts (1 + 2) * 3\n'),
    ('locals', 'a = 9\nb = 4\nputs a - b\n'),
    ('reassign', 'x = 1\nx = 2\nputs x\n'),
    ('if_else', 'x = 3\nif x > 2\n  puts 1\nelse\n  puts 0\nend\n'),
    ('unless', 'x = 3\nunless x > 2\n  puts 0\nelse\n  puts 1\nend\n'),
    ('elsif', 'x = 2\nif x == 1\n  puts 10\nelsif x == 2\n  puts 20\n'
              'else\n  puts 30\nend\n'),
    ('while', 'n = 0\nwhile n < 5\n  n += 1\nend\nputs n\n'),
    ('method', 'def add(a, b)\n  a + b\nend\nputs add(2, 3)\n'),
    ('zero_arg_method', 'def answer\n  42\nend\nputs answer\n'),
    ('nested_calls', 'def inc(n)\n  n + 1\nend\n'
                     'def twice(n)\n  inc(inc(n))\nend\nputs twice(5)\n'),
    ('recursion', 'def fib(n)\n  if n < 2\n    n\n  else\n'
                  '    fib(n - 1) + fib(n - 2)\n  end\nend\nputs fib(10)\n'),
    ('string', 's = "abc"\nputs s\n'),
    ('interpolation', 'n = 7\nputs "n=#{n}"\n'),
    ('two_interpolations', 'a = 2\nb = 3\nputs "#{a}+#{b}=#{a + b}"\n'),
    ('masgn', 'a, b = 1, 2\nputs a + b\n'),
    ('nil_true_false', 'puts nil\nputs true\nputs false\n'),
    ('comparison', 'puts 1 == 1\nputs 2 <= 3\nputs 3 >= 2\n'),
]

# bench_clock.rb needs RPyYARV's bench_now_ns, which CRuby does not have.
CRUBY_FILES = ['arith.rb', 'interpolation.rb', 'locals.rb', 'method_def.rb',
               'while_loop.rb']


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
    elif kind == rawiseq.OP_NIL:
        assert w_x is w_nil
    elif kind == rawiseq.OP_TRUE:
        assert w_x is w_true
    elif kind == rawiseq.OP_FALSE:
        assert w_x is w_false
    elif kind == rawiseq.OP_STR:
        assert isinstance(w_x, W_String)
        assert w_x.str_w() == raw_op.strval
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


def _audit_loaded(program, l):
    assert set(l.w_iseqs) <= set(range(len(program.iseqs)))
    for index, raw in enumerate(program.iseqs):
        if index not in l.w_iseqs:
            continue
        w_iseq = l.w_iseqs[index]
        assert w_iseq.name == raw.name
        assert w_iseq.nlocals == raw.nlocals
        assert w_iseq.stack_max == raw.stack_max
        assert w_iseq.nparams == raw.lead_num
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


@pytest.mark.parametrize('source', [source for _, source in CRUBY_CASES],
                         ids=[name for name, _ in CRUBY_CASES])
def test_loader_matches_cruby(source, compile_source, cruby_program, out):
    """Arbitrary supported source: the loaded ISeq must agree with CRuby."""
    text = compile_source(source)
    expected = cruby_program(source)
    program = iseqdump.parse(text)
    l = loader.Loader(program)
    w_iseq = l.load()
    _audit_loaded(program, l)
    run(w_iseq)
    assert out.text == expected


@pytest.mark.parametrize('name', CRUBY_FILES)
def test_loader_matches_cruby_file(name, compile_rb, ruby, out):
    """A .rb path is just another arbitrary ISeq to load and check."""
    path = os.path.join(HERE, 'ruby', name)
    expected = run_ruby_file(path, ruby)
    program = iseqdump.parse(compile_rb(path))
    l = loader.Loader(program)
    w_iseq = l.load()
    _audit_loaded(program, l)
    run(w_iseq)
    assert out.text == expected
