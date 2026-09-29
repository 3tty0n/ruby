"""Loader tests; the .iseq fixtures are real InstructionSequence output."""

import os

import insns
import iseqdump
import loader
from error import LoadError, UnsupportedOperation
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from objects.string import W_String
from objects.regexp import W_Regexp
from objects.transparent import W_Fixnum, w_nil
from support import HERE, fixture, run, run_dump

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


def _regexp_const(patched_operand):
    """Swaps fib(20)'s `putobject i:20` for a regexp literal operand and
    returns the W_Regexp the loader produced for it."""
    text = patched(fixture('fib_rec.iseq'), 'insn\tputobject\ti:20',
                   'insn\tputobject\t%s' % patched_operand)
    w_iseq = loader.load_dump(text)
    regexps = [w for w in w_iseq.consts if isinstance(w, W_Regexp)]
    assert len(regexps) == 1
    return regexps[0]


def test_regexp_literal_loaded():
    assert _regexp_const('x:/foo/').pattern == 'foo'
    # `//`: rfind still lands on the closing slash, not the opening one, so
    # this does not fall through to "no such object yet".
    assert _regexp_const('x://').pattern == ''


def test_regexp_literal_is_a_rough_slice_of_inspect():
    """Documents current behaviour: the loader takes everything between the
    first and the *last* '/', so flags are dropped and an escaped in-pattern
    '/' is kept raw. Both are known gaps in this temporary implementation
    (see loader.py's OP_OTHER branch, added by 58c6a10c7b)."""
    assert _regexp_const('x:/foo/i').pattern == 'foo'
    assert _regexp_const('x:/foo/mix').pattern == 'foo'
    assert _regexp_const('x:/a\\\\/b/').pattern == 'a\\/b'


def test_locals_end_to_end():
    # f(9, 4)
    w_iseq = loader.load_dump(fixture('locals.iseq'))
    assert run(w_iseq).int_w() == 5
    w_body = w_iseq.consts[0]
    assert isinstance(w_body, W_ISeq)
    # locals are [a, b, c]
    assert w_body.nlocals == 3
    assert w_body.nparams == 2
    assert w_body.code[0] == insns.GETLOCAL and w_body.code[1] == 0
    assert w_body.code[2] == insns.GETLOCAL and w_body.code[3] == 1
    assert w_body.code[5] == insns.SETLOCAL and w_body.code[6] == 2


def test_nested_iseq():
    w_iseq = loader.load_dump(fixture('fib_rec.iseq'))
    assert w_iseq.code[0] == insns.DEFINEMETHOD
    w_body = w_iseq.consts[w_iseq.code[2]]
    assert isinstance(w_body, W_ISeq)
    assert w_body.name == 'fib'
    assert w_body.nparams == 1
    assert w_body.simple_params
    calls = [w for w in w_body.consts if isinstance(w, W_CallInfo)]
    assert len(calls) > 0
    for w_ci in calls:
        assert w_ci.simple
    assert [w_ci.argc for w_ci in calls] == [1] * len(calls)


def test_specialized_variants_and_const_pool():
    w_body = loader.load_dump(fixture('fib_rec.iseq')).consts[0]
    assert insns.GETLOCAL in w_body.code
    assert insns.PUTOBJECT in w_body.code
    values = [w.int_w() for w in w_body.consts if isinstance(w, W_Fixnum)]
    assert 1 in values           # folded out of putobject_INT2FIX_1_
    # `putobject 2` appears three times in the body
    assert values.count(2) == 1


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
    at = w_iseq.code.index(insns.SEND)
    assert w_iseq.code[at + 2] == NO_BLOCK_ISEQ
    w_ci = w_iseq.consts[w_iseq.code[at + 1]]
    assert isinstance(w_ci, W_CallInfo)
    assert not w_ci.simple


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
    text = patched(fixture('fib_rec.iseq'), 'insn\tputself', 'insn\tputself\ti')
    expect(LoadError, text, 'malformed operand: i')
