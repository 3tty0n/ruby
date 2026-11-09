"""Unit tests for the interpreter loop: instructions, calls, classes."""

import pytest

from rpyyarv import insns
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.frame import Frame
from rpyyarv.iseq import W_CallInfo, NO_BLOCK_ISEQ
from rpyyarv.methods import W_CFunc, W_ISeqMethod
from rpyyarv.objects.instance import W_Object
from rpyyarv.objects.klass import (W_Class, w_array_class, w_class_class,
                                   w_float_class, w_integer_class,
                                   w_object_class, w_string_class)
from rpyyarv.objects.main import W_Main, w_main
from rpyyarv.objects.string import W_String
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.regexp import W_Regexp
from rpyyarv.objects.transparent import W_Fixnum, w_nil, w_true, w_false
from rpyyarv.test.support import asm, capture, expect_unsupported, run_dump




def test_arith():
    # (1 + 2) * 4 - 5
    iseq = asm([W_Fixnum(1), W_Fixnum(2), W_Fixnum(4), W_Fixnum(5)], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_PLUS,
        insns.PUTOBJECT, 2,
        insns.OPT_MULT,
        insns.PUTOBJECT, 3,
        insns.OPT_MINUS,
        insns.LEAVE,
    ])
    assert interp.run(iseq).int_w() == 7


def test_locals():
    iseq = asm([W_Fixnum(42)], 2, 4, [
        insns.PUTOBJECT, 0,
        insns.SETLOCAL, 1, 0,
        insns.GETLOCAL, 1, 0,
        insns.LEAVE,
    ])
    assert interp.run(iseq).int_w() == 42
    iseq2 = asm([], 2, 4, [insns.GETLOCAL, 0, 0, insns.LEAVE])
    assert interp.run(iseq2) is w_nil


def _branchif_taken(w_value):
    iseq = asm([w_value, W_Fixnum(0), W_Fixnum(1)], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.BRANCHIF, 'taken',
        insns.PUTOBJECT, 1,
        insns.LEAVE,
        ':taken',
        insns.PUTOBJECT, 2,
        insns.LEAVE,
    ])
    return interp.run(iseq).int_w() == 1


def test_falsiness():
    # 0 is truthy in Ruby
    assert _branchif_taken(W_Fixnum(0))
    assert _branchif_taken(W_Fixnum(1))
    assert _branchif_taken(w_true)
    assert not _branchif_taken(w_nil)
    assert not _branchif_taken(w_false)


def test_loop_sum():
    # local 0 = i, local 1 = sum
    iseq = asm([W_Fixnum(0), W_Fixnum(1), W_Fixnum(100)], 2, 4, [
        insns.PUTOBJECT, 0,
        insns.SETLOCAL, 1, 0,
        insns.PUTOBJECT, 1,
        insns.SETLOCAL, 0, 0,
        ':loop',
        insns.GETLOCAL, 0, 0,
        insns.PUTOBJECT, 2,
        insns.OPT_LE,
        insns.BRANCHUNLESS, 'end',
        insns.GETLOCAL, 1, 0,
        insns.GETLOCAL, 0, 0,
        insns.OPT_PLUS,
        insns.SETLOCAL, 1, 0,
        insns.GETLOCAL, 0, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_PLUS,
        insns.SETLOCAL, 0, 0,
        insns.JUMP, 'loop',
        ':end',
        insns.GETLOCAL, 1, 0,
        insns.LEAVE,
    ])
    assert interp.run(iseq).int_w() == 5050


def test_fib_iter():
    # locals: 0 = a, 1 = b, 2 = i, 3 = t
    iseq = asm([W_Fixnum(0), W_Fixnum(1), W_Fixnum(30)], 4, 4, [
        insns.PUTOBJECT, 0,
        insns.SETLOCAL, 0, 0,
        insns.PUTOBJECT, 1,
        insns.SETLOCAL, 1, 0,
        insns.PUTOBJECT, 0,
        insns.SETLOCAL, 2, 0,
        ':loop',
        insns.GETLOCAL, 2, 0,
        insns.PUTOBJECT, 2,
        insns.OPT_LT,
        insns.BRANCHUNLESS, 'end',
        insns.GETLOCAL, 0, 0,
        insns.GETLOCAL, 1, 0,
        insns.OPT_PLUS,
        insns.SETLOCAL, 3, 0,
        insns.GETLOCAL, 1, 0,
        insns.SETLOCAL, 0, 0,
        insns.GETLOCAL, 3, 0,
        insns.SETLOCAL, 1, 0,
        insns.GETLOCAL, 2, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_PLUS,
        insns.SETLOCAL, 2, 0,
        insns.JUMP, 'loop',
        ':end',
        insns.GETLOCAL, 0, 0,
        insns.LEAVE,
    ])
    assert interp.run(iseq).int_w() == 832040


def test_unsupported():
    iseq = asm([W_Fixnum(1)], 0, 4, [
        insns.PUTNIL,
        insns.PUTOBJECT, 0,
        insns.OPT_PLUS,
        insns.LEAVE,
    ])
    try:
        interp.run(iseq)
    except UnsupportedOperation as e:
        assert e.msg == "undefined method '+' for nil"
    else:
        raise AssertionError('expected UnsupportedOperation')

    iseq2 = asm([], 0, 4, [999])
    try:
        interp.run(iseq2)
    except UnsupportedOperation as e:
        assert e.msg == 'unknown opcode 999'
    else:
        raise AssertionError('expected UnsupportedOperation')


def test_pop_clears():
    iseq = asm([W_Fixnum(7)], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.DUP,
        insns.POP,
        insns.LEAVE,
    ])
    frame = Frame(iseq)
    assert interp.execute(iseq, frame).int_w() == 7
    assert frame.sp == 0
    for i in range(iseq.stack_max):
        assert frame.peek(i) is None

    frame2 = Frame(iseq)
    w_x = W_Fixnum(1)
    frame2.push(w_x)
    assert frame2.peek(0) is w_x
    assert frame2.pop() is w_x
    assert frame2.peek(0) is None
    assert frame2.sp == 0


def test_putself():
    iseq = asm([], 0, 1, [insns.PUTSELF, insns.LEAVE])
    w_self = W_Main()
    assert interp.execute(iseq, Frame(iseq, w_self)) is w_self
    assert interp.run(iseq) is w_main


def _add_iseq():
    # def add(a, b) = a + b
    return asm([], 2, 2, [
        insns.GETLOCAL, 0, 0,
        insns.GETLOCAL, 1, 0,
        insns.OPT_PLUS,
        insns.LEAVE,
    ], name='add', nparams=2)


def _sub_iseq():
    # def sub(a, b) = a - b
    return asm([], 2, 2, [
        insns.GETLOCAL, 0, 0,
        insns.GETLOCAL, 1, 0,
        insns.OPT_MINUS,
        insns.LEAVE,
    ], name='sub', nparams=2)


def test_definemethod_and_call():
    add_id = symbols.intern('add')
    w_body = _add_iseq()
    # add(3, 4)
    iseq = asm([w_body, W_Fixnum(3), W_Fixnum(4), W_CallInfo(add_id, 2)],
               0, 4, [
        insns.DEFINEMETHOD, add_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.PUTOBJECT, 2,
        insns.OPT_SEND_WITHOUT_BLOCK, 3,
        insns.LEAVE,
    ])
    w_self = W_Main()
    # A toplevel `def` lands on Object, not on a singleton class of main.
    assert w_object_class.find_method(add_id) is None
    frame = Frame(iseq, w_self)
    assert interp.execute(iseq, frame).int_w() == 7
    w_method = w_object_class.find_method(add_id)
    assert isinstance(w_method, W_ISeqMethod)
    assert w_method.w_iseq is w_body
    assert frame.sp == iseq.nlocals
    for i in range(iseq.stack_max):
        assert frame.peek(iseq.nlocals + i) is None


def test_argument_order():
    # sub(9, 4)
    sub_id = symbols.intern('sub')
    iseq = asm([_sub_iseq(), W_Fixnum(9), W_Fixnum(4), W_CallInfo(sub_id, 2)],
               0, 4, [
        insns.DEFINEMETHOD, sub_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.PUTOBJECT, 2,
        insns.OPT_SEND_WITHOUT_BLOCK, 3,
        insns.LEAVE,
    ])
    assert interp.execute(iseq, Frame(iseq, W_Main())).int_w() == 5


def _fib_program(n):
    """What CRuby compiles for `def fib(n) ... end; fib(n)`."""
    fib_id = symbols.intern('fib')
    w_body = asm([W_Fixnum(2), W_Fixnum(1), W_CallInfo(fib_id, 1)], 1, 6, [
        insns.GETLOCAL, 0, 0,
        insns.PUTOBJECT, 0,
        insns.OPT_LT,
        insns.BRANCHUNLESS, 'rec',
        insns.GETLOCAL, 0, 0,
        insns.LEAVE,
        ':rec',
        insns.PUTSELF,
        insns.GETLOCAL, 0, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_MINUS,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.PUTSELF,
        insns.GETLOCAL, 0, 0,
        insns.PUTOBJECT, 0,
        insns.OPT_MINUS,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.OPT_PLUS,
        insns.LEAVE,
    ], name='fib', nparams=1)
    return asm([w_body, W_Fixnum(n), W_CallInfo(fib_id, 1)], 0, 4, [
        insns.DEFINEMETHOD, fib_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.LEAVE,
    ])


def _fib(n):
    iseq = _fib_program(n)
    return interp.execute(iseq, Frame(iseq, W_Main())).int_w()


def test_fib_recursive():
    assert _fib(0) == 0
    assert _fib(1) == 1
    assert _fib(2) == 1
    assert _fib(10) == 55
    assert _fib(20) == 6765


def test_send_without_block():
    add_id = symbols.intern('add')
    iseq = asm([_add_iseq(), W_Fixnum(20), W_Fixnum(22),
                W_CallInfo(add_id, 2)], 0, 4, [
        insns.DEFINEMETHOD, add_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.PUTOBJECT, 2,
        insns.SEND, 3, NO_BLOCK_ISEQ,
        insns.LEAVE,
    ])
    assert interp.execute(iseq, Frame(iseq, W_Main())).int_w() == 42


def test_an_iseq_method_takes_a_block_it_never_yields_to():
    add_id = symbols.intern('add')
    w_block = asm([], 0, 1, [insns.PUTNIL, insns.LEAVE], name='block in add')
    iseq = asm([_add_iseq(), W_Fixnum(1), W_Fixnum(2),
                W_CallInfo(add_id, 2), w_block], 0, 4, [
        insns.DEFINEMETHOD, add_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.PUTOBJECT, 2,
        insns.SEND, 3, 4,
        insns.LEAVE,
    ])
    assert interp.execute(iseq, Frame(iseq, W_Main())).int_w() == 3


def test_a_block_runs_under_the_self_it_was_written_in():
    class W_CallIt(W_CFunc):
        def call(self, w_recv, args_w, w_block):
            return interp.call_block(w_block, [])

    call_id = symbols.intern('call_it')
    w_self = W_Main()
    w_self.define_method(call_id, W_CallIt(call_id, 0))
    w_block = asm([], 0, 1, [insns.PUTSELF, insns.LEAVE],
                  name='block in test')
    # 5.call_it { self } -- the receiver is 5, the block's self is w_self
    iseq = asm([W_Fixnum(5), W_CallInfo(call_id, 0), w_block], 0, 2, [
        insns.PUTOBJECT, 0,
        insns.SEND, 1, 2,
        insns.LEAVE,
    ])
    assert interp.execute(iseq, Frame(iseq, w_self)) is w_self


def _yield_one(w_arg):
    """call_it { |a, b| b } where the builtin call_it yields only w_arg."""
    class W_CallIt(W_CFunc):
        def call(self, w_recv, args_w, w_block):
            return interp.call_block(w_block, [w_arg])

    call_id = symbols.intern('call_it')
    w_self = W_Main()
    w_self.define_method(call_id, W_CallIt(call_id, 0))
    w_block = asm([], 2, 1, [insns.GETLOCAL, 1, 0, insns.LEAVE],
                  name='block in test', nparams=2)
    iseq = asm([W_CallInfo(call_id, 0), w_block], 0, 2, [
        insns.PUTSELF,
        insns.SEND, 0, 1,
        insns.LEAVE,
    ])
    return iseq, w_self


def test_a_missing_block_argument_is_nil():
    iseq, w_self = _yield_one(W_Fixnum(7))
    assert interp.execute(iseq, Frame(iseq, w_self)) is w_nil


def test_a_block_does_not_splat_an_array_yet():
    iseq, w_self = _yield_one(W_Array([W_Fixnum(1), W_Fixnum(2)]))
    expect_unsupported(iseq, w_self,
                       "block 'block in test' would splat its Array "
                       "argument, which RPyYARV does not support yet")



def test_inject_with_an_initial_value():
    inject_id = symbols.intern('inject')
    w_block = asm([], 2, 2, [
        insns.GETLOCAL, 0, 0,
        insns.GETLOCAL, 1, 0,
        insns.OPT_PLUS,
        insns.LEAVE,
    ], name='block in test', nparams=2)
    items = [W_Fixnum(1), W_Fixnum(2), W_Fixnum(3), W_Fixnum(4)]
    # [1, 2, 3, 4].inject(0) { |s, x| s + x }
    iseq = asm([W_Array(items), W_Fixnum(0), W_CallInfo(inject_id, 1), w_block],
               0, 4, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.SEND, 2, 3,
        insns.LEAVE,
    ])
    assert interp.run(iseq).int_w() == 10

def test_inject_needs_a_block():
    inject_id = symbols.intern('inject')
    # [1].inject(0) -- no block, so there is nothing to fold with
    iseq = asm([W_Array([W_Fixnum(1)]), W_Fixnum(0),
                W_CallInfo(inject_id, 1)], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(),
                       "inject without a block is not supported: RPyYARV has "
                       "no Symbol, so inject(:+) cannot work")


def test_wrong_argc():
    add_id = symbols.intern('add')
    iseq = asm([_add_iseq(), W_Fixnum(1), W_CallInfo(add_id, 1)], 0, 4, [
        insns.DEFINEMETHOD, add_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.LEAVE,
    ])
    expect_unsupported(
        iseq, W_Main(),
        "wrong number of arguments to 'add' (given 1, expected 2)")


def test_undefined_method():
    nope_id = symbols.intern('nope')
    iseq = asm([W_CallInfo(nope_id, 0)], 0, 4, [
        insns.PUTSELF,
        insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(), "undefined method 'nope' for main")
    expect_unsupported(iseq, w_nil, "undefined method 'nope' for nil")


def test_unsupported_call_shapes():
    add_id = symbols.intern('add')
    iseq = asm([_add_iseq(), W_Fixnum(1), W_Fixnum(2),
                W_CallInfo(add_id, 2, False)], 0, 4, [
        insns.DEFINEMETHOD, add_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.PUTOBJECT, 2,
        insns.OPT_SEND_WITHOUT_BLOCK, 3,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(),
                       "call to 'add' passes arguments RPyYARV does not "
                       "support")

    opt_id = symbols.intern('opt')
    w_body = asm([], 2, 2, [insns.GETLOCAL, 0, 0, insns.LEAVE],
                 name='opt', nparams=1, simple_params=False)
    iseq2 = asm([w_body, W_Fixnum(1), W_CallInfo(opt_id, 1)], 0, 4, [
        insns.DEFINEMETHOD, opt_id, 0,
        insns.PUTSELF,
        insns.PUTOBJECT, 1,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.LEAVE,
    ])
    expect_unsupported(
        iseq2, W_Main(),
        "method 'opt' has parameters RPyYARV does not support")


def test_definemethod_needs_a_receiver_with_a_table():
    m_id = symbols.intern('m')
    iseq = asm([_add_iseq()], 0, 1, [
        insns.DEFINEMETHOD, m_id, 0,
        insns.PUTNIL,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, w_nil, 'cannot define a method on nil')



def test_string_literal_and_concat():
    # "ab" + "c" as the compiler builds an interpolation
    iseq = asm([W_String('ab'), W_String('c')], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.CONCATSTRINGS, 2,
        insns.LEAVE,
    ])
    w_str = interp.run(iseq)
    assert isinstance(w_str, W_String)
    assert w_str.str_w() == 'abc'
    assert w_str.to_s_str() == 'abc'
    assert w_str.is_true()


def test_putchilledstring_copies_the_constant():
    # Chilled strings must be independently mutable later, so the constant
    # pool's literal is never pushed directly -- a fresh copy is made.
    w_lit = W_String('hi')
    iseq = asm([w_lit], 0, 1, [
        insns.PUTCHILLEDSTRING, 0,
        insns.LEAVE,
    ])
    w_ret = interp.run(iseq)
    assert isinstance(w_ret, W_String)
    assert w_ret.str_w() == 'hi'
    assert w_ret is not w_lit


def test_concatstrings_needs_strings():
    iseq = asm([W_Fixnum(1), W_String('x')], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.CONCATSTRINGS, 2,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(), 'not a string')


def test_string_plus():
    iseq = asm([W_String('4'), W_String('2')], 0, 2, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_PLUS,
        insns.LEAVE,
    ])
    w_str = interp.run(iseq)
    assert isinstance(w_str, W_String)
    assert w_str.str_w() == '42'


def test_to_s_str():
    assert W_Fixnum(-7).to_s_str() == '-7'
    assert w_nil.to_s_str() == ''
    assert w_true.to_s_str() == 'true'
    assert w_false.to_s_str() == 'false'


def test_objtostring():
    # dup / objtostring / anytostring, the interpolation shape
    iseq = asm([W_Fixnum(832040)], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.DUP,
        insns.OBJTOSTRING,
        insns.ANYTOSTRING,
        insns.LEAVE,
    ])
    assert interp.run(iseq).str_w() == '832040'

    # a String is already its own to_s
    w_str = W_String('done')
    iseq2 = asm([w_str], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.OBJTOSTRING,
        insns.LEAVE,
    ])
    assert interp.run(iseq2) is w_str


def test_objtostring_without_to_s():
    iseq = asm([asm([], 0, 1, [insns.LEAVE], name='inner')], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.OBJTOSTRING,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(), 'no class for <W_ISeq inner>')


def _interpolate(w_x):
    # "#{x}": x, dup, objtostring, anytostring
    iseq = asm([w_x], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.DUP,
        insns.OBJTOSTRING,
        insns.ANYTOSTRING,
        insns.LEAVE,
    ])
    return interp.run(iseq).str_w()


def test_objtostring_calls_a_user_defined_to_s():
    to_s_id = symbols.intern('to_s')
    w_foo = W_Class('Foo', w_object_class)
    w_body = asm([W_String('custom')], 0, 1, [insns.PUTOBJECT, 0, insns.LEAVE])
    w_foo.add_method(to_s_id, W_ISeqMethod(to_s_id, w_body))
    assert _interpolate(W_Object(w_foo)) == 'custom'


def test_toplevel_to_s_does_not_capture_builtin_classes():
    # `def to_s` at toplevel replaces Object#to_s; Integer, nil, true, false
    # and String keep their own, as in CRuby.
    to_s_id = symbols.intern('to_s')
    w_body = asm([W_String('X')], 0, 1, [insns.PUTOBJECT, 0, insns.LEAVE])
    w_object_class.add_method(to_s_id, W_ISeqMethod(to_s_id, w_body, True))
    assert _interpolate(W_Object(w_object_class)) == 'X'
    assert _interpolate(W_Fixnum(7)) == '7'
    assert _interpolate(w_nil) == ''
    assert _interpolate(w_true) == 'true'
    assert _interpolate(w_false) == 'false'


def test_main_to_s():
    assert _interpolate(w_main) == 'main'


def test_anytostring_needs_a_string():
    iseq = asm([W_Fixnum(1), W_Fixnum(2)], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.ANYTOSTRING,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(), 'to_s on 1 did not return a String')


def _puts_iseq(consts, argc):
    items = [insns.PUTSELF]
    for i in range(argc):
        items.append(insns.PUTOBJECT)
        items.append(i)
    items.append(insns.OPT_SEND_WITHOUT_BLOCK)
    items.append(len(consts) - 1)
    items.append(insns.LEAVE)
    return asm(consts, 0, 4, items)


def test_puts():
    puts_id = symbols.intern('puts')
    iseq = _puts_iseq([W_String('hi'), W_Fixnum(7), W_CallInfo(puts_id, 2)], 2)
    printed, w_ret = capture(lambda: interp.run(iseq))
    assert printed == 'hi\n7\n'
    assert w_ret is w_nil

    iseq2 = _puts_iseq([W_CallInfo(puts_id, 0)], 0)
    printed2, w_ret2 = capture(lambda: interp.run(iseq2))
    assert printed2 == '\n'
    assert w_ret2 is w_nil


def test_puts_adds_a_newline_only_when_missing():
    puts_id = symbols.intern('puts')
    iseq = _puts_iseq([W_String('a\n'), W_String(''), W_String('b\n\n'),
                       W_CallInfo(puts_id, 3)], 3)
    printed, _ = capture(lambda: interp.run(iseq))
    assert printed == 'a\n\nb\n\n'


def test_puts_calls_a_user_defined_to_s():
    puts_id = symbols.intern('puts')
    to_s_id = symbols.intern('to_s')
    w_foo = W_Class('Foo', w_object_class)
    w_body = asm([W_String('custom')], 0, 1, [insns.PUTOBJECT, 0, insns.LEAVE])
    w_foo.add_method(to_s_id, W_ISeqMethod(to_s_id, w_body))
    iseq = asm([W_CallInfo(puts_id, 1)], 0, 3, [
        insns.PUTSELF, insns.PUTSELF, insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE])
    w_self = W_Object(w_foo)
    printed, _ = capture(lambda: interp.execute(iseq, Frame(iseq, w_self)))
    assert printed == 'custom\n'


def test_puts_needs_to_s_to_return_a_string():
    puts_id = symbols.intern('puts')
    to_s_id = symbols.intern('to_s')
    w_foo = W_Class('Foo', w_object_class)
    w_body = asm([W_Fixnum(1)], 0, 1, [insns.PUTOBJECT, 0, insns.LEAVE])
    w_foo.add_method(to_s_id, W_ISeqMethod(to_s_id, w_body))
    iseq = asm([W_CallInfo(puts_id, 1)], 0, 3, [
        insns.PUTSELF, insns.PUTSELF, insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE])
    w_self = W_Object(w_foo)
    try:
        capture(lambda: interp.execute(iseq, Frame(iseq, w_self)))
    except UnsupportedOperation as e:
        assert e.msg == 'to_s on #<Foo> did not return a String'
    else:
        raise AssertionError('expected UnsupportedOperation')


def test_puts_is_private():
    puts_id = symbols.intern('puts')
    iseq = asm([W_Fixnum(1), W_Fixnum(2), W_CallInfo(puts_id, 1, True, False)],
               0, 3, [insns.PUTOBJECT, 0, insns.PUTOBJECT, 1,
                      insns.OPT_SEND_WITHOUT_BLOCK, 2, insns.LEAVE])
    expect_unsupported(iseq, W_Main(), "private method 'puts' called for 1")

def test_to_i():
    to_i_id = symbols.intern('to_i')

    def to_i_of(s):
        iseq = asm([W_String(s), W_CallInfo(to_i_id, 0)], 0, 2, [
            insns.PUTOBJECT, 0,
            insns.OPT_SEND_WITHOUT_BLOCK, 1,
            insns.LEAVE,
        ])
        return interp.run(iseq).int_w()

    assert to_i_of('42') == 42
    assert to_i_of('  42') == 42
    assert to_i_of('-5') == -5
    assert to_i_of('+7') == 7
    assert to_i_of('1_000') == 1000
    assert to_i_of('1__000') == 1
    assert to_i_of('_1') == 0
    assert to_i_of('1_') == 1
    assert to_i_of('5abc') == 5
    assert to_i_of('abc') == 0
    assert to_i_of('') == 0
    assert to_i_of('\xef\xbc\x91\xef\xbc\x92') == 0
    assert to_i_of('0x10') == 0
    assert to_i_of('  -0012x') == -12
    assert to_i_of('\t\n 9') == 9
    assert to_i_of('- 5') == 0
    assert to_i_of('0d12') == 12
    assert to_i_of('-0d12') == -12
    assert to_i_of('0d_1') == 0
    try:
        to_i_of('99999999999999999999')
    except UnsupportedOperation:
        pass
    else:
        raise AssertionError('expected UnsupportedOperation')

def test_to_s():
    to_s_id = symbols.intern('to_s')

    def to_s_of(w_recv):
        iseq = asm([w_recv, W_CallInfo(to_s_id, 0)], 0, 2, [
            insns.PUTOBJECT, 0,
            insns.OPT_SEND_WITHOUT_BLOCK, 1,
            insns.LEAVE,
        ])
        return interp.run(iseq).str_w()

    assert to_s_of(W_Fixnum(42)) == '42'
    assert to_s_of(W_String('hi')) == 'hi'
    assert to_s_of(w_nil) == ''
    assert to_s_of(w_true) == 'true'
    assert to_s_of(w_false) == 'false'

def test_bench_now_ns():
    now_id = symbols.intern('bench_now_ns')
    iseq = asm([W_CallInfo(now_id, 0)], 0, 1, [
        insns.PUTSELF,
        insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE,
    ])
    t0 = interp.run(iseq).int_w()
    t1 = interp.run(iseq).int_w()
    assert t0 > 0
    assert t1 >= t0

def test_split_on_empty_regexp():
    split_id = symbols.intern('split')

    def split_of(s):
        iseq = asm([W_String(s), W_Regexp(''), W_CallInfo(split_id, 1)],
                   0, 3, [
            insns.PUTOBJECT, 0,
            insns.PUTOBJECT, 1,
            insns.OPT_SEND_WITHOUT_BLOCK, 2,
            insns.LEAVE,
        ])
        w_ary = interp.run(iseq)
        assert isinstance(w_ary, W_Array)
        return [w.str_w() for w in w_ary.items()]

    assert split_of('1021') == ['1', '0', '2', '1']
    assert split_of('') == []
    assert split_of('\xe3\x81\x82\xe3\x81\x84') == ['\xe3\x81\x82',
                                                    '\xe3\x81\x84']
    assert split_of('\xf0\x9f\x98\x80x') == ['\xf0\x9f\x98\x80', 'x']
    assert split_of('a\xcc\x81') == ['a', '\xcc\x81']


def test_split_rejects_invalid_utf8():
    split_id = symbols.intern('split')
    for s in ['\xff', '\xe3\x81', '\xe0\x80\x80', '\xed\xa0\x80']:
        iseq = asm([W_String(s), W_Regexp(''), W_CallInfo(split_id, 1)],
                   0, 3, [
            insns.PUTOBJECT, 0,
            insns.PUTOBJECT, 1,
            insns.OPT_SEND_WITHOUT_BLOCK, 2,
            insns.LEAVE,
        ])
        expect_unsupported(iseq, W_Main(),
                           'split on "%s": invalid byte sequence in UTF-8' % s)
    # Strings are bytes (RPython str; the tests model that with latin-1).
    assert split_of('a\xc3\xa9\xe2\x82\xac\xf0\x9f\x98\x80') == [
        'a', '\xc3\xa9', '\xe2\x82\xac', '\xf0\x9f\x98\x80']
    # a broken sequence is one char per byte, as String#each_char has it
    assert split_of('\xe3\x81') == ['\xe3', '\x81']
    assert split_of('\xe3a') == ['\xe3', 'a']
    assert split_of('\xff\x80') == ['\xff', '\x80']
    assert split_of('\xc0\x80') == ['\xc0', '\x80']          # overlong
    assert split_of('\xed\xa0\x80') == ['\xed', '\xa0', '\x80']  # surrogate
    assert split_of('\xf4\x90\x80\x80') == ['\xf4', '\x90', '\x80', '\x80']


def test_split_needs_an_empty_regexp():
    split_id = symbols.intern('split')
    iseq = asm([W_String('a,b'), W_Regexp(','), W_CallInfo(split_id, 1)],
               0, 3, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(),
                       "split on /,/: RPyYARV only supports split(//) so far")


def test_cfunc_arity_is_checked():
    class W_One(W_CFunc):
        def call(self, w_recv, args_w, w_block):
            return args_w[0]

    one_id = symbols.intern('one')
    w_self = W_Main()
    w_self.define_method(one_id, W_One(one_id, 1))
    iseq = asm([W_Fixnum(1), W_Fixnum(2), W_CallInfo(one_id, 2)], 0, 4, [
        insns.PUTSELF,
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.LEAVE,
    ])
    expect_unsupported(
        iseq, w_self,
        "wrong number of arguments to 'one' (given 2, expected 1)")


def test_a_block_reaches_a_cfunc():
    class W_Twice(W_CFunc):
        def call(self, w_recv, args_w, w_block):
            w_once = interp.call_block(w_block, [args_w[0]])
            return interp.call_block(w_block, [w_once])

    twice_id = symbols.intern('twice')
    w_self = W_Main()
    w_self.define_method(twice_id, W_Twice(twice_id, 1))
    w_block = asm([], 1, 2, [
        insns.GETLOCAL, 0, 0,
        insns.GETLOCAL, 0, 0,
        insns.OPT_PLUS,
        insns.LEAVE,
    ], name='block in test', nparams=1)
    # twice(3) { |x| x + x }
    iseq = asm([W_Fixnum(3), W_CallInfo(twice_id, 1), w_block], 0, 4, [
        insns.PUTSELF,
        insns.PUTOBJECT, 0,
        insns.SEND, 1, 2,
        insns.LEAVE,
    ])
    assert interp.execute(iseq, Frame(iseq, w_self)).int_w() == 12


def test_class_is_an_object():
    w_class = W_Class('Foo', w_object_class)
    assert w_class.getclass() is w_class_class
    assert w_class_class.getclass() is w_class_class


def test_definemethod_in_a_class_body():
    # `class Foo; def bar; 42; end; end` runs the body with self = Foo.
    bar_id = symbols.intern('bar')
    body = asm([W_Fixnum(42)], 0, 2, [insns.PUTOBJECT, 0, insns.LEAVE],
               name='bar')
    iseq = asm([body], 0, 2, [
        insns.DEFINEMETHOD, bar_id, 0,
        insns.PUTNIL,
        insns.LEAVE,
    ])
    w_class = W_Class('Foo', w_object_class)
    interp.execute(iseq, Frame(iseq, w_class))
    assert w_class.find_method(bar_id) is not None
    assert w_object_class.find_method(bar_id) is None


def test_new_allocates_an_instance():
    w_class = W_Class('Foo', w_object_class)
    w_obj = _send_new(w_class, [])
    assert isinstance(w_obj, W_Object)
    assert w_obj.getclass() is w_class
    assert w_obj.repr() == '#<Foo>'
    assert _send_new(w_class, []) is not w_obj


def test_new_runs_initialize():
    # def initialize(a); @x would go here; end -- proves args reach the body.
    seen = []

    class W_Init(W_CFunc):
        def call(self, w_recv, args_w, w_block):
            seen.append((w_recv, args_w[0].int_w()))
            return w_nil

    init_id = symbols.intern('initialize')
    w_class = W_Class('Foo', w_object_class)
    w_class.add_method(init_id, W_Init(init_id, 1))
    w_obj = _send_new(w_class, [W_Fixnum(7)])
    assert seen == [(w_obj, 7)]


def test_new_without_initialize_rejects_arguments():
    w_class = W_Class('Foo', w_object_class)
    try:
        _send_new(w_class, [W_Fixnum(1)])
    except UnsupportedOperation as e:
        assert e.msg == ("wrong number of arguments to 'initialize' "
                         "(given 1, expected 0)")
    else:
        raise AssertionError('expected UnsupportedOperation')


def test_instance_method_is_found_through_its_class():
    bar_id = symbols.intern('bar')
    body = asm([W_Fixnum(42)], 0, 2, [insns.PUTOBJECT, 0, insns.LEAVE],
               name='bar')
    w_class = W_Class('Foo', w_object_class)
    w_class.add_method(bar_id, W_ISeqMethod(bar_id, body))
    w_obj = _send_new(w_class, [])
    iseq = asm([W_CallInfo(bar_id, 0)], 1, 2, [
        insns.GETLOCAL, 0, 0,
        insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE,
    ])
    frame = Frame(iseq, w_main)
    frame.setlocal(0, w_obj)
    assert interp.execute(iseq, frame).int_w() == 42


def test_new_is_not_inherited_by_instances():
    w_class = W_Class('Foo', w_object_class)
    w_obj = _send_new(w_class, [])
    new_id = symbols.intern('new')
    iseq = asm([W_CallInfo(new_id, 0)], 1, 2, [
        insns.GETLOCAL, 0, 0,
        insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE,
    ])
    frame = Frame(iseq, w_main)
    frame.setlocal(0, w_obj)
    try:
        interp.execute(iseq, frame)
    except UnsupportedOperation as e:
        assert e.msg == "undefined method 'new' for #<Foo>"
    else:
        raise AssertionError('expected UnsupportedOperation')


def test_toplevel_def_is_private():
    # def helper; 42; end -- reachable as `helper`, not as `1.helper`.
    helper_id = symbols.intern('helper')
    body = asm([W_Fixnum(42)], 0, 2, [insns.PUTOBJECT, 0, insns.LEAVE],
               name='helper')

    def iseq_calling(recv_insns, fcall):
        return asm([body, W_CallInfo(helper_id, 0, True, fcall),
                    W_Fixnum(42)], 0, 4,
                   [insns.DEFINEMETHOD, helper_id, 0] + recv_insns +
                   [insns.OPT_SEND_WITHOUT_BLOCK, 1, insns.LEAVE])

    iseq = iseq_calling([insns.PUTSELF], True)
    assert interp.execute(iseq, Frame(iseq, W_Main())).int_w() == 42
    assert w_object_class.find_method(helper_id).private

    iseq2 = iseq_calling([insns.PUTOBJECT, 2], False)
    expect_unsupported(iseq2, W_Main(),
                       "private method 'helper' called for 42")


def test_method_in_a_class_body_is_public():
    bar_id = symbols.intern('bar')
    body = asm([W_Fixnum(1)], 0, 2, [insns.PUTOBJECT, 0, insns.LEAVE],
               name='bar')
    iseq = asm([body], 0, 2, [
        insns.DEFINEMETHOD, bar_id, 0, insns.PUTNIL, insns.LEAVE])
    w_class = W_Class('Foo', w_object_class)
    interp.execute(iseq, Frame(iseq, w_class))
    assert not w_class.find_method(bar_id).private


def _send_new(w_class, args_w):
    """Foo.new(*args) through the interpreter's own dispatch."""
    new_id = symbols.intern('new')
    items = [insns.GETLOCAL, 0, 0]
    consts = [W_CallInfo(new_id, len(args_w))]
    for i in range(len(args_w)):
        consts.append(args_w[i])
        items += [insns.PUTOBJECT, i + 1]
    items += [insns.OPT_SEND_WITHOUT_BLOCK, 0, insns.LEAVE]
    iseq = asm(consts, 1, 4 + len(args_w), items)
    frame = Frame(iseq, w_main)
    frame.setlocal(0, w_class)
    return interp.execute(iseq, frame)


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


@pytest.mark.parametrize('source, msg', [
    ('def !\n  1\nend\n!nil\n', "private method '!' called for nil"),
    ('def ==(o)\n  1\nend\nnil == 2\n',
     "private method '==' called for nil")])
def test_a_private_operator_method_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source', [
    'a = [0]\na[0] = a\na.join(",")\n',
    'a = [0]\nb = [a]\na[0] = b\na.join(",")\n',
    'a = [0]\na[0] = [[a]]\na.join(",")\n'])
def test_a_recursive_join_is_refused(source, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None,
                       'recursive array join (ArgumentError)')


def test_a_tail_call_without_a_block_drops_the_callers_block(compile_source):
    source = ('def t(n)\n  if n == 0 then yield else t(n - 1) end\nend\n'
              't(1) { puts 1 }\n')
    expect_unsupported(loader.load_dump(compile_source(source)), None,
                       'no block given (yield)')


def test_aset_below_the_start_is_refused(compile_source):
    expect_unsupported(
        loader.load_dump(compile_source('a = [1, 2, 3]\na[-5] = 0\n')), None,
        'index -5 too small for array; minimum: -3')


@pytest.mark.parametrize('source, msg', [
    ('class Foo < Array\nend\n',
     'subclassing the built-in class Array is not supported yet'),
    ('class A\nend\nclass B\nend\nclass C < A\nend\nclass C < B\nend\n',
     'superclass mismatch for class C'),
    ('class A < 3\nend\n',
     'superclass must be an instance of Class (given an instance of Integer)'),
    ('X = 1\nclass X\nend\n', 'X is not a class')])
def test_a_class_definition_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('class Foo\n  puts X\nend\n', 'uninitialized constant Foo::X'),
    ('class Foo\nend\nputs Foo::Array\n',
     'uninitialized constant Foo::Array'),
    ('X = 1\nY = X::Z\n', '1 is not a class/module')])
def test_a_constant_lookup_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('class Foo\n  def initialize\n  end\nend\nFoo.new.initialize\n',
     "private method 'initialize' called for #<Foo>"),
    ('class Foo\n  def initialize(a, b)\n  end\nend\nFoo.new(1)\n',
     "wrong number of arguments to 'initialize' (given 1, expected 2)"),
    ('puts Hash.new.length\n', 'Hash.new is not supported yet')])
def test_an_instance_creation_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('class Foo\n  attr_reader 1\nend\n', '1 is not a symbol nor a string'),
    ('class Foo\n  attr_reader :a?\nend\n', "invalid attribute name 'a?'"),
    ('attr_reader :x\n', "undefined method 'attr_reader' for main")])
def test_an_attribute_definition_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('class K\n  def self.a\n    1\n  end\nend\nK.new.a\n',
     "undefined method 'a' for #<K>"),
    ('class K\n  def self.a\n    1\n  end\nend\nclass L\nend\nL.a\n',
     "undefined method 'a' for L"),
    ('s = Object.new\ndef s.hi\n  1\nend\n',
     'a singleton method on #<Object> is not supported yet')])
def test_a_singleton_method_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('class A\n  def f\n    super\n  end\nend\nA.new.f\n',
     "super: no superclass method 'f' for #<A>"),
    ('def g\n  super\nend\ng\n', "super: no superclass method 'g' for main")])
def test_a_super_call_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('h = {}\nh[1.5] = 1\n', 'a Hash key of class Float is not supported yet'),
    ('h = {1 => 2}\nh[[1]]\n',
     'a Hash key of class Array is not supported yet'),
    ('h = {1 => 2}\nh.each { |k, v| h[k + 1] = v }\n',
     "can't add a new key into hash during iteration"),
    ('{1 => 2}.each\n',
     'each without a block (an Enumerator) is not supported yet')])
def test_a_hash_operation_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('def f(a)\nend\nf(*[1, 2])\n',
     "wrong number of arguments to 'f' (given 2, expected 1)"),
    ('class U\n  def to_a\n    1\n  end\nend\n[*U.new]\n',
     "can't convert U to Array (U#to_a gives Integer)"),
    ('def f\n  yield(*[1])\nend\nf { |x| x }\n',
     'yield passes arguments RPyYARV does not support'),
    ('class A\n  def f(x)\n  end\nend\nclass B < A\n  def f(x)\n'
     '    super(*[x])\n  end\nend\nB.new.f(1)\n',
     'super passes arguments RPyYARV does not support')])
def test_a_splat_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ("x = 'a'\n(1..x)\n", 'bad value for range'),
    ('x = []\n(x..x)\n', 'a Range of Array is not supported yet'),
    ('(1.0..2.0).each { }\n', 'each over Float..Float is not supported yet'),
    ("('a'..'c').each { }\n",
     'each over String..String is not supported yet'),
    ('(1..).to_a\n', 'to_a over Integer..NilClass is not supported yet'),
    ('(0..10).step(0) { }\n', "step can't be 0"),
    ('(0..10).step(2)\n',
     'step without a block (an ArithmeticSequence) is not supported yet'),
    ('(0..1).step(0.5) { }\n', 'step by Float is not supported yet')])
def test_a_range_operation_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('3.times.map\n',
     'map without a block (an Enumerator) is not supported yet'),
    ('3.times.map(&:to_s)\n',
     "call to 'map' passes arguments RPyYARV does not support"),
    ('3.times.to_h\n',
     "undefined method 'to_h' for #<Enumerator: 3:times>")])
def test_a_times_enumerator_operation_is_refused(source, msg,
                                                 compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('1 + "a"\n', "String can't be coerced into Integer"),
    ('1 - nil\n', "nil can't be coerced into Integer"),
    ('1.0 * :a\n', ":a can't be coerced into Float"),
    ('class C\nend\n1 / C.new\n', "C can't be coerced into Integer"),
    ('1 < "a"\n', 'comparison of Integer with String failed'),
    ('1.5 >= true\n', 'comparison of Float with true failed'),
    ('class K\n  def coerce(o)\n    [o, 1]\n  end\nend\n1 + K.new\n',
     '+ with K through coerce is not supported yet'),
    ('"a" + 1\n', 'no implicit conversion of Integer into String'),
    ('"a" + nil\n', 'no implicit conversion of nil into String'),
    ('"a" + :b\n', 'no implicit conversion of Symbol into String'),
    ('class S\n  def to_str\n    "s"\n  end\nend\n"a" + S.new\n',
     '+ with S through to_str is not supported yet')])
def test_an_operator_on_a_wrong_type_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


class W_Redefined(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return W_String('redefined')


@pytest.fixture
def redefine():
    """Defines a method on a built-in class as Ruby code would, then
    undoes it."""
    saved = []

    def define(w_class, name):
        saved.append((w_class, w_class.methods.methods.copy(),
                      w_class.redefined))
        mid = symbols.intern(name)
        w_class.add_user_method(mid, W_Redefined(mid, -1))
    yield define
    for w_class, methods, redefined in reversed(saved):
        w_class.methods.methods = methods
        w_class.redefined = redefined
        w_class.method_table_changed()


@pytest.mark.parametrize('w_class, name, source, expected', [
    (w_integer_class, '+', 'puts 1 + 2\n', 'redefined\n'),
    (w_integer_class, '<', 'puts 1 < 2\n', 'redefined\n'),
    (w_float_class, '*', 'puts 1.5 * 2\n', 'redefined\n'),
    (w_float_class, '*', 'puts 3 * 2\n', '6\n'),
    (w_integer_class, '==', 'puts 1 == 2\nputs [1] == [2]\n',
     'redefined\ntrue\n'),
    (w_integer_class, '!=', 'puts 1 != 2\n', 'redefined\n'),
    (w_string_class, '+', 'puts "a" + "b"\n', 'redefined\n'),
    (w_array_class, '[]', 'puts [1][0]\n', 'redefined\n'),
    (w_array_class, '[]=', 'a = [1]\na[0] = 2\nputs a[0]\n', '1\n'),
    (w_array_class, 'length', 'puts [1].length\nputs [1].size\n',
     'redefined\n1\n'),
    (w_array_class, 'size', 'puts [1].size\n', 'redefined\n')])
def test_a_redefined_builtin_method_is_called(w_class, name, source, expected,
                                              redefine, compile_source):
    redefine(w_class, name)
    out, _ = capture(lambda: run_dump(compile_source(source)))
    assert out == expected


@pytest.mark.parametrize('source, msg', [
    ('class Integer\n  def mark\n    @m = 1\n  end\nend\n1.mark\n',
     "cannot set instance variable '@m' on 1"),
    ('class Array\n  attr_writer :tag\nend\n[].tag = 1\n',
     "cannot set instance variable '@tag' on <W_Array 0>"),
    ('class Integer < Object\nend\n', 'superclass mismatch for class Integer')])
def test_reopening_a_builtin_class_is_refused_where_unsupported(
        source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('Array.new(-1)\n', 'negative array size'),
    ('Array.new("a")\n', 'no implicit conversion of String into Integer'),
    ('Array.new(nil)\n', 'no implicit conversion from nil to integer'),
    ('Array.new(1, 2, 3)\n',
     "wrong number of arguments to 'initialize' (given 3, expected 0..2)"),
    ('(1..2).dup\n', 'dup of <W_Range 1..2> is not supported yet')])
def test_an_array_new_or_dup_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('[1].at("x")\n', 'no implicit conversion of String into Integer'),
    ('[1].first(-1)\n', 'negative array size'),
    ('[1, 2].insert(-9, 0)\n',
     'index -9 too small for array; minimum: -3'),
    ('[1] + 1\n', 'no implicit conversion of Integer into Array'),
    ('[1] * -1\n', 'negative argument'),
    ('[1] * nil\n', 'no implicit conversion from nil to integer'),
    ('[1, 2].slice!(0..1)\n', 'slice! with a Range is not supported yet'),
    ('[1].pop(1, 2)\n',
     "wrong number of arguments to 'pop' (given 2, expected 0..1)"),
    ('puts ["a"].inspect\n', "undefined method 'inspect' for \"a\"")])
def test_an_array_method_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('1.step(3, nil) { }\n', 'step must be numeric'),
    ('1.step(3, 0.0) { }\n', "step can't be 0"),
    ('1.step(3, 1, 1) { }\n',
     "wrong number of arguments to 'step' (given 3, expected 0..2)"),
    ('1.step(nil) { }\n',
     'step without a limit (an endless loop) is not supported yet'),
    ('1.step(3, 1.5) { }\n', 'step by Float is not supported yet'),
    ('1.upto(2.5) { }\n', 'upto to Float is not supported yet'),
    ('(-8.0) ** 0.5\n',
     '-8.0 ** 0.5 is a Complex: RPyYARV has no Complex yet'),
    ('2.0 ** "a"\n', "String can't be coerced into Float")])
def test_a_numeric_method_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('(1..3).collect\n',
     'collect without a block (an Enumerator) is not supported yet'),
    ('(1..).map { }\n', 'map over Integer..NilClass is not supported yet'),
    ('class Range\n  def each\n  end\nend\n(1..3).map { }\n',
     'map after redefining Range#each is not supported yet'),
    ('class Range\n  def each\n  end\nend\n(1..3).to_a\n',
     'to_a after redefining Range#each is not supported yet')])
def test_a_range_method_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('Math.sqrt(-1)\n', 'Numerical argument is out of domain - sqrt'),
    ('Math.sqrt(:a)\n', "can't convert Symbol into Float"),
    ('Math.sin(nil)\n', "can't convert nil into Float"),
    ('Math.cos("1")\n', "can't convert String into Float"),
    ('class Integer\n  def to_f\n  end\nend\nMath.sqrt(4)\n',
     'Math.sqrt after redefining Integer#to_f is not supported yet'),
    ('Math.new\n', "undefined method 'new' for Math"),
    ('class X < Math\nend\n',
     'superclass must be an instance of Class (given an instance of '
     'Module)'),
    ('class Math\nend\n', 'Math is not a class')])
def test_math_is_refused_where_cruby_raises(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('def f(a, *r)\nend\nf\n',
     "wrong number of arguments to 'f' (given 0, expected 1+)"),
    ('class A\n  def m(*a)\n  end\nend\nclass B < A\n  def m(*a)\n'
     '    super\n  end\nend\nB.new.m(1)\n',
     'super passes arguments RPyYARV does not support')])
def test_rest_parameters_are_refused_where_unsupported(source, msg,
                                                       compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('"%d" % 1\n', 'format %d is not supported yet'),
    ('"x%.2f" % 1.0\n', 'format x%.2f is not supported yet'),
    ('"%.2f" % 1\n', 'format %.2f of Integer is not supported yet'),
    ('Integer(3.7)\n', 'Integer() of Float is not supported yet'),
    ('Integer("1", 2)\n',
     'Integer() with a base or options is not supported yet')])
def test_a_format_or_integer_call_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('2 ** -1\n', '2 ** -1 is a Rational: RPyYARV has no Rational yet'),
    ('0 ** -1\n', 'divided by 0 (ZeroDivisionError)'),
    ('3 ** 40\n', '3 ** 40 overflows a Fixnum: RPyYARV has no Bignum yet'),
    ('(-8) ** 0.5\n',
     '-8.0 ** 0.5 is a Complex: RPyYARV has no Complex yet'),
    ('x = -9223372036854775807 - 1\n-x\n',
     '-(-9223372036854775808) overflows a Fixnum: RPyYARV has no Bignum '
     'yet')])
def test_an_integer_power_or_negation_is_refused(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('undef foo\n', "undefined method 'foo' for class 'Object'"),
    ('alias a b\n', "undefined method 'b' for class 'Object'"),
    ('class C\n  undef foo\nend\n', "undefined method 'foo' for class 'C'"),
    ('class C\n  def a\n  end\n  undef a\nend\nC.new.a\n',
     "undefined method 'a' for #<C>"),
    ('class P\n  def a\n  end\nend\nclass Q < P\n  undef a\nend\n'
     'Q.new.a\n', "undefined method 'a' for #<Q>"),
    ('alias say puts\nsay.say\n', "private method 'say' called for nil")])
def test_alias_and_undef_follow_cruby(source, msg, compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)


@pytest.mark.parametrize('source, msg', [
    ('case 2\nwhen (1..3) then 1\nend\n', 'Range#=== is not supported yet'),
    ('case "a"\nwhen /a/ then 1\nend\n', 'Regexp#=== is not supported yet')])
def test_case_equality_is_refused_where_unsupported(source, msg,
                                                    compile_source):
    expect_unsupported(loader.load_dump(compile_source(source)), None, msg)
