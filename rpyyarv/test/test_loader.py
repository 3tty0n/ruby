import os

import pytest

from rpyyarv import insns
from rpyyarv import iseqdump
from rpyyarv import loader
from rpyyarv.error import LoadError, UnsupportedOperation
from rpyyarv.iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from rpyyarv.objects.string import W_String
from rpyyarv.objects.regexp import W_Regexp
from rpyyarv.objects.transparent import w_nil
from rpyyarv.test.support import (HERE, check_loaded, decode, defined_method,
                                  expect_unsupported, fixture, only_insn, run,
                                  run_dump, run_ruby_file)


def expect(exc_class, text, msg):
    with pytest.raises(exc_class) as info:
        loader.load_dump(text)
    assert info.value.msg == msg


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
        (insns.GETLOCAL, [0, 0]),
        (insns.GETLOCAL, [1, 0]),
        (insns.OPT_MINUS, []),
        (insns.SETLOCAL, [2, 0]),
        (insns.GETLOCAL, [2, 0]),
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


def _putobject_slots(w_body):
    return [operands[0] for _, op, operands in decode(w_body)
            if op == insns.PUTOBJECT]


def test_specialized_variants_lower_to_putobject():
    w_body = _fib_body()
    puts = _putobject_slots(w_body)
    # putobject 2, putobject_INT2FIX_1_, putobject 2
    assert [w_body.consts[i].int_w() for i in puts] == [2, 1, 2]


def test_equal_fixnum_literals_share_a_pool_slot():
    puts = _putobject_slots(_fib_body())
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
                   'insn\topt_reverse\ti:0\ninsn\topt_reverse\ti:0\n'
                   'insn\tputstring\ts:x\n'
                   'insn\tputself\ninsn\tgetlocal_WC_0\ti:3')
    expect(UnsupportedOperation, text,
           '2 unimplemented instruction(s) in 3 occurrence(s): '
           'opt_reverse x2, putstring x1')


def test_a_block_local_names_its_enclosing_scope():
    w_block = loader.load_dump(fixture('block.iseq')).consts[1]
    _, operands = only_insn(w_block, insns.GETLOCAL)
    assert operands == [0, 1]


def test_a_level_beyond_the_nesting_is_refused():
    text = patched(fixture('block.iseq'), 'insn\tgetlocal_WC_1\ti:3',
                   'insn\tgetlocal\ti:3\ti:2')
    expect(LoadError, text, "getlocal in 'block in <main>' reaches level 2, "
           "but it is nested only 1 deep")


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
                   'insn\tputobject\tx:1..2')
    expect(UnsupportedOperation, text,
           "putobject of object 1..2 in '<main>': RPyYARV has no such "
           "object yet")


def test_equal_symbol_literals_are_one_object(compile_source):
    w_iseq = loader.load_dump(compile_source(
        'def f\n  :abc\nend\ndef g\n  :abc\nend\n'))
    w_f = defined_method(w_iseq, 'f')
    w_g = defined_method(w_iseq, 'g')
    _, (f_idx,) = only_insn(w_f, insns.PUTOBJECT)
    _, (g_idx,) = only_insn(w_g, insns.PUTOBJECT)
    assert w_f.consts[f_idx] is w_g.consts[g_idx]


@pytest.mark.parametrize('params, simple', [
    ('', True), ('|e|', True), ('|a, b|', True), ('|a, |', False),
    ('|*a|', False), ('|a, b = 5|', False)])
def test_block_params_are_simple_only_when_plain(params, simple,
                                                 compile_source):
    w_iseq = loader.load_dump(compile_source('1.times { %s nil }\n' % params))
    _, (_, block_idx) = only_insn(w_iseq, insns.SEND)
    assert w_iseq.consts[block_idx].simple_params == simple


def test_a_block_with_a_rest_parameter_is_refused(compile_source):
    w_iseq = loader.load_dump(compile_source('1.times { |*a| a }\n'))
    expect_unsupported(w_iseq, None, "block 'block in <main>' has parameters "
                       "RPyYARV does not support")


@pytest.mark.parametrize('source, msg', [
    ('a = 4611686018427387903\nb = a + a + 1\nb + 1\n',
     '9223372036854775807 + 1'),
    ('a = -4611686018427387904\nb = a + a\nb - 1\n',
     '-9223372036854775808 - 1'),
    ('3037000500 * 3037000500\n', '3037000500 * 3037000500')])
def test_integer_overflow_is_refused(source, msg, compile_source):
    w_iseq = loader.load_dump(compile_source(source))
    expect_unsupported(w_iseq, None,
                       msg + ' overflows a Fixnum: RPyYARV has no Bignum yet')


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
    ('puts_newline', 'puts "a\\n"\nputs ""\nputs "b\\n\\n"\n'),
    ('to_s_main', 'puts self\nputs "#{self}"\n'),
    ('to_s_redefined', 'def to_s\n  "X"\nend\nputs "#{1}"\nputs "#{nil}"\n'
                       'puts "#{true}"\n'),
    ('to_s_main_redefined', 'def to_s\n  "X"\nend\nputs self\nputs "#{self}"\n'),
    ('split_utf8', 'a, b, c, d = "a\\u00e9\\u20ac\\u{1F600}".split(//)\n'
                   'puts a\nputs b\nputs c\nputs d\n'),
    ('nil_true_false', 'puts nil\nputs true\nputs false\n'),
    ('comparison', 'puts 1 == 1\nputs 2 <= 3\nputs 3 >= 2\n'),
    ('float_to_s', 'puts 4.2\nputs 100.0\nputs 1e15\nputs 1.5e16\n'
                   'puts 1234567890123456.7\nputs 0.0001\nputs 0.00001\n'
                   'puts 2.5e-10\nputs -0.0\nputs -3.25\nputs 1e400\n'
                   'puts -1e400\nputs 1e100\n'),
    ('float_arith', 'puts 1 + 2.5\nputs 0.1 + 0.2\nputs 2.5 * 4\n'
                    'puts 1.5 - 3\nputs 3 - 1.5\nputs "#{1.5}"\n'),
    ('float_compare', 'puts 1 < 1.5\nputs 1.5 > 2\nputs 2.0 <= 2\n'
                      'puts 2 >= 2.5\nputs 2.0 == 2\nputs 0.1 + 0.2 == 0.3\n'),
    ('numeric_methods', 'puts 42.real?\nputs 4.2.real?\nputs 42.real\n'
                        'puts 4.2.real\nputs 42.imag\nputs 4.2.imag\n'
                        'puts 42.conj\nputs 4.2.conj\nputs 42.integer?\n'
                        'puts 4.2.integer?\nputs 42.finite?\n'
                        'puts 42.infinite?\nputs 42.numerator\n'
                        'puts 42.denominator\n'),
    ('float_methods', 'f = 4.2\nn = -4.2\nz = -0.0\nputs f.to_f\n'
                      'puts n.abs\nputs n.magnitude\nputs z.abs\nputs -f\n'
                      'puts -z\nputs 0.0.zero?\nputs z.zero?\nputs f.zero?\n'
                      'puts n.negative?\nputs z.negative?\nputs f.positive?\n'
                      'puts 0.0.positive?\nputs f.finite?\nputs f.infinite?\n'),
    ('float_special', 'inf = 1e400\nninf = -inf\nnan = inf - inf\n'
                      'puts inf.finite?\nputs nan.finite?\n'
                      'puts inf.infinite?\nputs ninf.infinite?\n'
                      'puts nan.infinite?\nputs nan.zero?\n'
                      'puts nan.positive?\nputs nan.negative?\n'
                      'puts nan.abs\nputs ninf.abs\n'),
    ('symbol', 'puts :abc\nx = :foo\nputs "a#{x}b"\nputs :abc.to_s\n'),
    ('times', '3.times { |i| puts i }\nputs 3.times { }\n'
              '0.times { puts 1 }\n2.times { puts "x" }\n'
              '2.times { |a, b| puts a\n  puts b }\n'),
    ('int_beyond_fixnum', 'puts 4611686018427387903 + 1\n'
                          'puts -4611686018427387904 - 1\n'
                          'puts 3037000499 * 3037000499\n'),
    ('block_reads_outer', 'x = 5\n1.times { puts x }\n'),
    ('block_writes_outer', 'sum = 0\n4.times { |i| sum += i }\nputs sum\n'),
    ('nested_blocks', 'a = 1\n1.times { b = 2\n  1.times { puts a + b\n'
                      '    a = 10 } }\nputs a\n'),
    ('block_in_method', 'def f(n)\n  t = 0\n  n.times { |i| t += i }\n'
                        '  t\nend\nputs f(5)\n'),
    ('array_literals', 'a = 1\nb = [a, a + 1, 3]\n'
                       'puts b.inject(0) { |s, x| s + x }\n'
                       'c = [1, 2]\nputs c.inject(10) { |s, x| s + x }\n'),
    ('array_index', 'a = [1, 2, 3]\nputs a[0]\nputs a[-1]\nputs a[5]\n'
                    'a[1] = 20\na[5] = 6\nputs a[1]\nputs a[4]\nputs a[5]\n'),
    ('stack_shuffles', 'a = [1, 2]\nputs(a[0] = 7)\na[1] += 10\nputs a[0]\n'
                       'puts a[1]\nb = a[0] = 3\nputs b\n'),
    ('length_size', 'a = [1, 2, 3]\nputs a.length\nputs a.size\n'
                    'puts "abc".size\nputs "a\\u00e9\\u20ac".length\n'
                    'puts [].size\n'),
    ('array_each_map_join', 'a = [1, 2, 3]\nt = 0\nr = a.each { |x| t += x }\n'
                            'puts t\nputs r.size\n'
                            'puts a.map { |x| x * 2 }.join(",")\n'
                            'puts [1, [2, [3, nil]], "s"].join("-")\n'
                            'puts a.join\n'),
    ('equality', 'puts 1 == 1.0\nputs 1 != 2\nputs 1 == nil\nputs nil == nil\n'
                 'puts "a" == "a"\nputs "a" != "b"\nputs :a == :a\n'
                 'puts [1, "x", [2]] == [1, "x", [2]]\nputs [1] == [2]\n'
                 'puts [1] != [1]\nputs !nil\nputs !1\nputs !!false\n'
                 'puts "a" == 1\n'),
    ('div_mod', 'puts 7 / 2\nputs -7 / 2\nputs 7 / -2\nputs 7 % 3\n'
                'puts -7 % 3\nputs 7 % -3\nputs 7.0 / 2\nputs 7 / 2.0\n'
                'puts 1.0 / 0\nputs -1.0 / 0\nputs 0.0 / 0\nputs 1.0 / -0.0\n'
                'puts 7.5 % 2\nputs -7.5 % 2\nputs 7.5 % -2\n'),
    ('ivars_on_main', '@a = 1\n@a += 2\nputs @a\nputs @b\n'
                      'def f\n  @a * 10\nend\nputs f\n'),
    ('constants', 'puts Array\nputs ::Integer\nputs Object\nx = Float\n'
                  'puts x == Float\nputs Array == Integer\n'),
]

# bench_clock.rb needs RPyYARV's bench_now_ns, which CRuby does not have.
CRUBY_FILES = ['arith.rb', 'interpolation.rb', 'locals.rb', 'method_def.rb',
               'while_loop.rb']



def _assert_matches_cruby(text, expected, out):
    """Loads text, audits it against its raw ISeqs, runs it, compares stdout."""
    program = iseqdump.parse(text)
    l = loader.Loader(program)
    w_iseq = l.load()
    check_loaded(program, l)
    run(w_iseq)
    assert out.text == expected


@pytest.mark.parametrize('source', [source for _, source in CRUBY_CASES],
                         ids=[name for name, _ in CRUBY_CASES])
def test_loader_matches_cruby(source, compile_source, cruby_program, out):
    """Arbitrary supported source: the loaded ISeq must agree with CRuby."""
    _assert_matches_cruby(compile_source(source), cruby_program(source), out)


@pytest.mark.parametrize('name', CRUBY_FILES)
def test_loader_matches_cruby_file(name, compile_rb, ruby, out):
    """A .rb path is just another arbitrary ISeq to load and check."""
    path = os.path.join(HERE, 'ruby', name)
    _assert_matches_cruby(compile_rb(path), run_ruby_file(path, ruby), out)
