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
                                  fixture, only_insn, run, run_dump,
                                  run_ruby_file)


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
                   'insn\tputstring\ts:x\ninsn\tintern\n'
                   'insn\tputstring\ts:y\n'
                   'insn\tputself\ninsn\tputobject')
    l = loader.Loader(iseqdump.parse(text))
    l.scan()
    assert l.missing == {'putstring': 2, 'intern': 1}
    assert l.missing_names == ['putstring', 'intern']
    expect(UnsupportedOperation, text,
           '2 unimplemented instruction(s) in 3 occurrence(s): '
           'putstring x2, intern x1')


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


def test_a_hash_literal_with_an_unsupported_key_is_refused(compile_source):
    expect(UnsupportedOperation, compile_source('{1.5 => 1}\n'),
           'a Hash key of class Float is not supported yet')


@pytest.mark.parametrize('source', ['module M\nend\n',
                                    'class << self\nend\n'])
def test_a_module_or_singleton_class_is_refused_at_load(source,
                                                        compile_source):
    expect(UnsupportedOperation, compile_source(source),
           "defineclass of a module or a singleton class in '<main>' is not "
           "supported")


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
                    'puts [].size\nputs "\\xE3\\x81".length\n'
                    'puts "\\x80ab\\xF0\\x9F\\x98".size\n'),
    ('array_each_map_join', 'a = [1, 2, 3]\nt = 0\nr = a.each { |x| t += x }\n'
                            'puts t\nputs r.size\n'
                            'puts a.map { |x| x * 2 }.join(",")\n'
                            'puts [1, [2, [3, nil]], "s"].join("-")\n'
                            'puts a.join\n'),
    ('array_join_nested', 'puts [1, [], 2].join("-")\nputs [1, []].join(",")\n'
                          'puts [[[]]].join(",")\n'
                          'puts [1, [2, []], 3].join("-")\n'
                          'puts [1, 2].join(nil)\n'),
    ('array_mutated_in_loop', 'a = [1, 2]\nr = []\n'
                              'a.each { |x| r[r.size] = x\n'
                              '  a[a.size] = 9 if a.size < 4 }\n'
                              'puts r.join(",")\nb = [1, 2, 3]\n'
                              'puts b.map { |x| b[2] = 7 if x == 1\n  x }.join(",")\n'),
    ('equality', 'puts 1 == 1.0\nputs 1 != 2\nputs 1 == nil\nputs nil == nil\n'
                 'puts "a" == "a"\nputs "a" != "b"\nputs :a == :a\n'
                 'puts [1, "x", [2]] == [1, "x", [2]]\nputs [1] == [2]\n'
                 'puts [1] != [1]\nputs !nil\nputs !1\nputs !!false\n'
                 'puts "a" == 1\n'),
    ('equality_identity', 'n = 0.0 / 0\nputs n == n\nputs [n] == [n]\n'
                          'puts [n] != [n]\nputs [0.0 / 0] == [0.0 / 0]\n'),
    ('equality_recursive', 'a = [0]\na[0] = a\nb = [0]\nb[0] = b\n'
                           'puts a == a\nputs a == b\nputs a != b\n'),
    ('equality_num_reverses', 'def ==(o)\n  true\nend\nputs 1 == nil\n'
                              'puts 1.0 == nil\nputs 1 != nil\n'),
    ('equality_resized', 'def ==(o)\n  @a[3] = 0\n  true\nend\n@a = [self]\n'
                         'puts @a == [nil]\n'),
    ('join_repeated', 'a = [1, 2]\nputs [a, a].join(",")\n'
                      'puts [[a], a].join("-")\n'),
    ('float_mod_inf', 'i = 1.0 / 0\nputs i % 2\nputs -i % 2\nputs i % i\n'
                      'puts 5 % i\nputs -1.0 % i\n'),
    ('int_mod_min', 'a = -4611686018427387904\nb = a + a\nputs b % -1\n'
                    'puts b % 3\n'),
    ('duparray_copies', '2.times { a = [1, 2]; a[0] += 10; puts a[0] }\n'),
    ('attr_op_assign', 'def foo\n  @foo\nend\ndef foo=(v)\n  @foo = v\nend\n'
                       '@foo = 1\nself.foo += 4\nputs foo\n'),
    ('aset_or_assign', 'a = [1, nil]\na[0] ||= 5\na[1] ||= 6\nputs a[0]\n'
                       'puts a[1]\nx = (a[0] ||= 9)\nputs x\n'),
    ('class_definition', 'x = class Foo\n  puts self\n  def hi\n    1\n  end\n'
                         '  42\nend\nputs x\nclass Foo\n  puts 1\nend\n'
                         'class Bar < Foo\nend\nputs Bar\nputs Foo == Bar\n'
                         'class Foo\n  class Inner\n    puts self\n  end\n'
                         'end\nputs Foo::Inner\n'
                         'puts((class Baz; end) == nil)\n'
                         'class Bar < Foo\n  puts 2\nend\n'
                         '[1].each { class Qux; puts self; end }\n'),
    ('constant_set', 'X = 1\nputs X\nY = X + 1\nputs Y\nputs ::X\n'
                     'class Foo\nend\nFoo::K = 7\nputs Foo::K\nF = Foo\n'
                     'class F\n  puts self\nend\n'),
    ('constant_lexical', 'A = 1\nclass Outer\n  A = 2\n  class Inner\n'
                         '    puts A\n  end\n  puts A\n  class Array\n  end\n'
                         '  puts Array\n  puts ::Array\n'
                         '  [1].each { |x| puts A + x }\nend\nputs A\n'
                         'puts Array\nputs Outer::Inner\n'),
    ('constant_ancestors', 'class Base\n  K = :base\nend\nK = :top\n'
                           'class Sub < Base\n  puts K\nend\n'
                           'class Outer\n  K = :outer\n'
                           '  class Sub2 < Base\n    puts K\n  end\nend\n'
                           'puts Sub::K\ndef top_k\n  K\nend\nputs top_k\n'),
    ('new_initialize',
     'class Point\n  def initialize(x, y)\n    @x = x\n    @y = y\n  end\n'
     '  def sum\n    @x + @y\n  end\nend\np = Point.new(3, 4)\nputs p.sum\n'
     'q = Point.new(10, 20)\nputs q.sum\nputs p.sum\n'
     'class Foo\n  def hi\n    :hi\n  end\nend\nputs Foo.new.hi\n'
     'class B < Point\nend\nputs B.new(1, 2).sum\nf = Foo.new\n'
     'puts f == f\nputs f == Foo.new\nputs Object.new == nil\n'
     'puts Foo.new.to_s.length\n'),
    ('new_in_loop_and_block',
     'class C\n  def initialize(i)\n    @i = yield(i)\n  end\n'
     '  def i\n    @i\n  end\nend\ns = 0\n'
     '10.times { |i| s += C.new(i) { |x| x * 2 }.i }\nputs s\n'),
    ('user_operators',
     'class V\n  def initialize(x)\n    @x = x\n  end\n  def x\n    @x\n  end\n'
     '  def +(o)\n    V.new(@x + o.x)\n  end\n  def -(o)\n    V.new(@x - o.x)\n'
     '  end\n  def *(o)\n    V.new(@x * o.x)\n  end\n  def <(o)\n    @x < o.x\n'
     '  end\n  def >=(o)\n    @x >= o.x\n  end\nend\n'
     'puts (V.new(1) + V.new(2)).x\nputs (V.new(5) - V.new(2)).x\n'
     'puts (V.new(3) * V.new(4)).x\nputs V.new(1) < V.new(2)\n'
     'puts V.new(1) >= V.new(2)\n'),
    ('attr_accessors',
     'class P\n  attr_accessor :x, "y"\n  attr_reader :r\n  attr_writer :w\n'
     '  def initialize\n    @r = 9\n  end\n  def w_value\n    @w\n  end\nend\n'
     'p = P.new\nputs p.x == nil\np.x = 5\nputs p.x\np.y = 6\nputs p.y\n'
     'puts p.r\np.w = 7\nputs p.w_value\nputs((p.x = 8))\nputs p.x\n'
     'p.x += 1\nputs p.x\nclass T < P\nend\nt = T.new\nt.x = 4\nputs t.x\n'),
    ('attr_return_values',
     'class Q\n  a = attr_accessor :a, "b"\n  puts a.length\n  puts a[1]\n'
     '  puts attr_reader(:c)[0]\n  puts attr_writer(:d)[0]\n'
     '  attr_accessor :A\nend\nq = Q.new\nq.A = 1\nputs q.A\n'),
    ('class_methods',
     'class Point\n  attr_reader :x\n  V = 5\n  def initialize(x)\n'
     '    @x = x\n  end\n  def self.origin\n    new(0)\n  end\n'
     '  def self.twice(n)\n    n * 2 + v\n  end\n  def self.v\n    V\n'
     '  end\nend\nputs Point.origin.x\nputs Point.twice(21)\n'
     'puts(def Point.three; 3; end)\nputs Point.three\n'
     'def Integer.half(n)\n  n / 2\nend\nputs Integer.half(9)\n'),
    ('class_methods_inherited',
     'class A\n  def self.make\n    new\n  end\n  def self.name_of\n    :a\n'
     '  end\nend\nclass B < A\n  def self.name_of\n    :b\n  end\nend\n'
     'puts B.make == nil\nputs A.name_of\nputs B.name_of\n'
     'class C < B\nend\nputs C.name_of\ndef A.late\n  :late\nend\n'
     'puts C.late\nclass Foo\n  def self.new(x)\n    x * 10\n  end\nend\n'
     'puts Foo.new(4)\n'),
    ('super_calls',
     'class A\n  attr_reader :a\n  def initialize(a)\n    super()\n'
     '    @a = a\n  end\n  def f(x)\n    x * 10\n  end\n'
     '  def self.make\n    :a\n  end\nend\nclass B < A\n'
     '  def initialize(a, b)\n    super(a)\n    @b = b\n  end\n'
     '  def f(x)\n    r = super(x + 1) + super\n    x = 7\n    r + super\n'
     '  end\n  def self.make\n    [super, :b].join("+")\n  end\nend\n'
     'class C < B\nend\nclass D < C\n  def f(x)\n    super * 2\n  end\n'
     'end\nputs B.new(1, 2).a\nputs B.new(1, 2).f(2)\nputs D.new(1, 2).f(2)\n'
     'puts B.make\nputs D.make\n'),
    ('super_blocks',
     'class A\n  def f(x)\n    yield(x) + 1\n  end\nend\nclass B < A\n'
     '  def f(x)\n    super + super(x) { |v| v * 100 }\n  end\nend\n'
     'class C < A\n  def f(x)\n    r = 0\n    [1].each { |i| r = super(x + i) }\n'
     '    r\n  end\nend\nputs B.new.f(2) { |v| v }\n'
     'puts C.new.f(1) { |v| v * 3 }\n'),
    ('class_scoped', 'class Base\n  class X\n  end\nend\nclass Sub < Base\n'
                     'end\nclass Sub::X\n  puts self\nend\n'
                     'puts Sub::X == Base::X\nclass Top\nend\n'
                     'class Sub::Top\nend\nputs Sub::Top == Top\n'
                     'class Sub::X\n  puts 1\nend\n'),
    ('yield_tail_new_block', 'def u(n)\n  if n == 0 then yield else '
                             'u(n - 1) { puts n } end\nend\nu(1) { puts 9 }\n'),
    ('yield_through_iseq_block', 'def inner\n  yield 2\nend\ndef outer_m\n'
                                 '  inner { |x| yield x * 3 }\nend\n'
                                 'outer_m { |y| puts y }\n'),
    ('int_float_exact', 'a = 9007199254740993\nf = 9007199254740992.0\n'
                        'puts a == f\nputs a > f\nputs f < a\nputs a <= f\n'
                        'puts a != f\nputs 1 == 1.0\nputs -0.0 == 0\n'
                        'nan = 0.0 / 0\nputs 1 < nan\nputs 1 >= nan\n'
                        'puts 1 != nan\nputs 4611686018427387903 < 1e19\n'
                        'puts 1 > -1e400\nputs 2.5 > 2\nputs 2 >= 2.0\n'),
    ('div_mod', 'puts 7 / 2\nputs -7 / 2\nputs 7 / -2\nputs 7 % 3\n'
                'puts -7 % 3\nputs 7 % -3\nputs 7.0 / 2\nputs 7 / 2.0\n'
                'puts 1.0 / 0\nputs -1.0 / 0\nputs 0.0 / 0\nputs 1.0 / -0.0\n'
                'puts 7.5 % 2\nputs -7.5 % 2\nputs 7.5 % -2\n'),
    ('ivars_on_main', '@a = 1\n@a += 2\nputs @a\nputs @b\n'
                      'def f\n  @a * 10\nend\nputs f\n'),
    ('constants', 'puts Array\nputs ::Integer\nputs Object\nx = Float\n'
                  'puts x == Float\nputs Array == Integer\n'),
    ('yield', 'def f\n  yield 1, 2\nend\nf { |a, b| puts a + b }\n'
              'def g(n)\n  n.times { |i| yield i * 10 }\nend\n'
              'g(3) { |x| puts x }\ndef h\n  yield\nend\nputs h { 5 }\n'
              'def c(x)\n  x\nend\nputs c(7) { 1 }\n'),
    ('hash', 'h = {1 => :a, "s" => 2, nil => 3, true => 4, :k => false}\n'
             'puts h[1]\nputs h["s"]\nputs h[nil]\nputs h[true]\n'
             'puts h[:k]\nputs h[:none]\nputs h.size\nputs h.length\n'
             'puts h.key?("s")\nputs h.key?(2)\nputs h.keys[4]\n'
             'puts h.values[1]\nputs({} == {})\n'),
    ('hash_order', 'x = 3\ng = {x => 1, "a" => x, x => 2}\ng[9] = 1\n'
                   'g[3] = 5\nputs g.size\ng.each { |k, v| puts k\n'
                   '  puts v }\ng.each { |pair| puts pair[0] }\n'
                   'g.each { |k, v| g[k] = 0 }\nputs g.values[2]\n'),
    ('hash_equal', 'puts({1 => 2} == {1 => 2})\nputs({1 => 2} == {1 => 3})\n'
                   'puts({1 => 2} == {2 => 2})\nputs({1 => 2} == {})\n'
                   'puts({1 => 1} == {1 => 1.0})\nputs({} == [])\n'
                   'puts({1 => 2} != {1 => 2})\na = {}\na[1] = a\nb = {}\n'
                   'b[1] = b\nputs a == b\n'),
    ('splat_call', 'def f(x, y, z)\n  puts x + y * z\nend\na = [2, 3]\n'
                   'f(1, *a)\nf(*a, 4)\nf(*[1, 2, 3])\nputs(*a)\n'
                   'class C\n  def initialize(x, y)\n    @s = x - y\n  end\n'
                   '  def s\n    @s\n  end\nend\nputs C.new(*a).s\n'
                   'def h(x)\n  yield x\nend\nh(*[5]) { |v| puts v }\n'),
    ('splat_array', 'a = [1, 2]\nb = 3\nx = [*a]\nx[0] = 9\nputs a[0]\n'
                    'puts [*a, b].join(",")\nputs [b, *a].join(",")\n'
                    'puts [*a, *a].join(",")\nputs [b, *a, b].join(",")\n'
                    'puts([*nil].size)\nputs [*1].join(",")\n'
                    'puts [*a, *nil].size\nputs [*a, *b].join(",")\n'
                    'class T\n  def to_a\n    [7, 8]\n  end\nend\n'
                    'puts [*T.new].join(",")\nputs [0, *T.new].join(",")\n'
                    'h = {1 => 2, 3 => 4}\nputs [*h][1].join(",")\n'
                    'puts h.to_a.size\n'),
    ('for_loop', 'for x in [7, 8] do puts x end\nputs x\n'
                 'for y in [[1, 2]] do puts y.size end\n'),
    ('range', 'r = (1..4)\nr.each { |i| puts i }\n(2...4).each { |i| puts i }\n'
              'n = 3\n(1..n).each { |i| puts i * 10 }\n'
              '(1...n).each { |i| puts i }\nfor i in 1..n do puts i end\n'
              'puts i\nputs((1..n).to_a.join(","))\nputs((5..1).to_a.size)\n'
              'puts((1...1).to_a.size)\n(0..10).step(4) { |i| puts i }\n'
              '(10..0).step(-3) { |i| puts i }\n'
              '(0..10).step(-1) { |i| puts i }\n'
              '(1...10).step(3) { |i| puts i }\nputs(r.each { } == r)\n'
              'puts((0..2).step(1) { } == (0..2))\n'),
    ('range_equal', 'puts((1..2) == (1..2))\nputs((1..2) == (1...2))\n'
                    'puts((1..2) == (1..2.0))\nputs((1..2) == (1..3))\n'
                    'puts((1..2) == [1, 2])\nputs((1..) == (1..))\n'
                    'puts(("a".."c") == ("a".."c"))\nx = 2\n'
                    'puts((..x) == (..2))\n'),
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
