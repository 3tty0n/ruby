"""Loader tests; the .iseq fixtures are real InstructionSequence output."""

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import insns
import interp
import iseqdump
import kernel
import loader
from error import LoadError, UnsupportedOperation
from frame import Frame
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from objects.string import W_String
from objects.main import W_Main
from objects.transparent import W_Fixnum, w_nil

DUMPER = os.path.join(_ROOT, 'scripts', 'dump_iseq.rb')
_BUILD = os.environ.get('RPYYARV_BUILD',
                        os.path.join(os.path.dirname(_ROOT), 'build'))


def build_ruby():
    """Only this tree's ruby emits instructions that match insns.py."""
    exe = os.environ.get('RUBY', os.path.join(_BUILD, 'ruby'))
    if not os.path.exists(exe):
        return None, None
    env = dict(os.environ)
    # The build tree's libruby is tagged with its install prefix, not its path
    for var in ('DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
        env[var] = os.pathsep.join([_BUILD] + [p for p in [env.get(var)] if p])
    return exe, env


def fixture(name):
    f = open(os.path.join(_HERE, name))
    try:
        return f.read()
    finally:
        f.close()


def run(text):
    """Runs on a self of its own, so tests cannot see each other."""
    w_iseq = loader.load_dump(text)
    return interp.execute(w_iseq, Frame(w_iseq, W_Main()))


def run_iseq(w_iseq):
    return interp.execute(w_iseq, Frame(w_iseq, W_Main()))


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
    assert run(fixture('fib_rec.iseq')).int_w() == 6765


def test_fib_rec_from_source():
    """.rb in, value out, when a ruby is around."""
    exe, env = build_ruby()
    if exe is None:
        print('   (no ruby in %s: fixture only)' % _BUILD)
        return
    try:
        text = subprocess.check_output(
            [exe, DUMPER, os.path.join(_HERE, 'fib_rec.rb')], env=env)
    except (OSError, subprocess.CalledProcessError):
        print('   (build ruby will not run: fixture only)')
        return
    if not isinstance(text, str):
        text = text.decode('utf-8')
    assert run(text).int_w() == 6765


def test_fib_iterative_end_to_end():
    # test/fib.rb, the interception fixture: interpolation, puts and all
    out = []
    saved = kernel.write
    kernel.write = lambda s: out.append(s)
    try:
        w_ret = run(fixture('fib.iseq'))
    finally:
        kernel.write = saved
    assert ''.join(out) == 'EXECUTED:832040\n'
    assert w_ret is w_nil


def test_string_literal_loaded():
    w_iseq = loader.load_dump(fixture('fib.iseq'))
    strings = [w.str_w() for w in w_iseq.consts if isinstance(w, W_String)]
    assert strings == ['EXECUTED:']


def test_locals_end_to_end():
    # f(9, 4)
    w_iseq = loader.load_dump(fixture('locals.iseq'))
    assert run_iseq(w_iseq).int_w() == 5
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


def _main():
    tests = []
    for name in globals().keys():
        if name.startswith('test_'):
            func = globals()[name]
            tests.append((func.__code__.co_firstlineno, name, func))
    tests.sort()
    for lineno, name, func in tests:
        func()
        print('ok %s' % name)
    print('%d passed' % len(tests))


if __name__ == '__main__':
    import traceback
    try:
        _main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
