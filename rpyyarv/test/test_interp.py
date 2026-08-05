import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import insns
import interp
import kernel
import symbols
from error import UnsupportedOperation
from frame import Frame
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from methods import W_CFunc, W_ISeqMethod, W_Method
from objects.instance import W_Object
from objects.klass import W_Class, w_class_class, w_object_class
from objects.main import W_Main, w_main
from objects.string import W_String
from objects.transparent import W_Fixnum, w_nil, w_true, w_false


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


def expect_unsupported(iseq, w_self, msg):
    try:
        interp.execute(iseq, Frame(iseq, w_self))
    except UnsupportedOperation as e:
        assert e.msg == msg, 'got %r, expected %r' % (e.msg, msg)
    else:
        raise AssertionError('expected UnsupportedOperation: %s' % msg)


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
        insns.SETLOCAL, 1,
        insns.GETLOCAL, 1,
        insns.LEAVE,
    ])
    assert interp.run(iseq).int_w() == 42
    iseq2 = asm([], 2, 4, [insns.GETLOCAL, 0, insns.LEAVE])
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
        insns.SETLOCAL, 1,
        insns.PUTOBJECT, 1,
        insns.SETLOCAL, 0,
        ':loop',
        insns.GETLOCAL, 0,
        insns.PUTOBJECT, 2,
        insns.OPT_LE,
        insns.BRANCHUNLESS, 'end',
        insns.GETLOCAL, 1,
        insns.GETLOCAL, 0,
        insns.OPT_PLUS,
        insns.SETLOCAL, 1,
        insns.GETLOCAL, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_PLUS,
        insns.SETLOCAL, 0,
        insns.JUMP, 'loop',
        ':end',
        insns.GETLOCAL, 1,
        insns.LEAVE,
    ])
    assert interp.run(iseq).int_w() == 5050


def test_fib_iter():
    # locals: 0 = a, 1 = b, 2 = i, 3 = t
    iseq = asm([W_Fixnum(0), W_Fixnum(1), W_Fixnum(30)], 4, 4, [
        insns.PUTOBJECT, 0,
        insns.SETLOCAL, 0,
        insns.PUTOBJECT, 1,
        insns.SETLOCAL, 1,
        insns.PUTOBJECT, 0,
        insns.SETLOCAL, 2,
        ':loop',
        insns.GETLOCAL, 2,
        insns.PUTOBJECT, 2,
        insns.OPT_LT,
        insns.BRANCHUNLESS, 'end',
        insns.GETLOCAL, 0,
        insns.GETLOCAL, 1,
        insns.OPT_PLUS,
        insns.SETLOCAL, 3,
        insns.GETLOCAL, 1,
        insns.SETLOCAL, 0,
        insns.GETLOCAL, 3,
        insns.SETLOCAL, 1,
        insns.GETLOCAL, 2,
        insns.PUTOBJECT, 1,
        insns.OPT_PLUS,
        insns.SETLOCAL, 2,
        insns.JUMP, 'loop',
        ':end',
        insns.GETLOCAL, 0,
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
        assert e.msg == 'not an integer'
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
    for slot in frame.stack:
        assert slot is None

    frame2 = Frame(iseq)
    w_x = W_Fixnum(1)
    frame2.push(w_x)
    assert frame2.stack[0] is w_x
    assert frame2.pop() is w_x
    assert frame2.stack[0] is None
    assert frame2.sp == 0


def test_putself():
    iseq = asm([], 0, 1, [insns.PUTSELF, insns.LEAVE])
    w_self = W_Main()
    assert interp.execute(iseq, Frame(iseq, w_self)) is w_self
    assert interp.run(iseq) is w_main


def _add_iseq():
    # def add(a, b) = a + b
    return asm([], 2, 2, [
        insns.GETLOCAL, 0,
        insns.GETLOCAL, 1,
        insns.OPT_PLUS,
        insns.LEAVE,
    ], name='add', nparams=2)


def _sub_iseq():
    # def sub(a, b) = a - b
    return asm([], 2, 2, [
        insns.GETLOCAL, 0,
        insns.GETLOCAL, 1,
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
    assert frame.sp == 0
    for slot in frame.stack:
        assert slot is None


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
        insns.GETLOCAL, 0,
        insns.PUTOBJECT, 0,
        insns.OPT_LT,
        insns.BRANCHUNLESS, 'rec',
        insns.GETLOCAL, 0,
        insns.LEAVE,
        ':rec',
        insns.PUTSELF,
        insns.GETLOCAL, 0,
        insns.PUTOBJECT, 1,
        insns.OPT_MINUS,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.PUTSELF,
        insns.GETLOCAL, 0,
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


def test_send_with_block_unsupported():
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
    expect_unsupported(iseq, W_Main(),
                       "send with a block is not supported: 'add'")


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
    w_body = asm([], 2, 2, [insns.GETLOCAL, 0, insns.LEAVE],
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


def test_concatstrings_needs_strings():
    iseq = asm([W_Fixnum(1), W_String('x')], 0, 4, [
        insns.PUTOBJECT, 0,
        insns.PUTOBJECT, 1,
        insns.CONCATSTRINGS, 2,
        insns.LEAVE,
    ])
    expect_unsupported(iseq, W_Main(), 'not a string')


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
    expect_unsupported(iseq, W_Main(), 'no to_s for <W_ISeq inner>')


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


def test_cfunc_arity_is_checked():
    class W_One(W_CFunc):
        def call(self, w_recv, args_w):
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
        def call(self, w_recv, args_w):
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
        assert e.msg == ("wrong number of arguments to 'new' "
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
        insns.GETLOCAL, 0,
        insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE,
    ])
    frame = Frame(iseq, w_main)
    frame.locals[0] = w_obj
    assert interp.execute(iseq, frame).int_w() == 42


def test_new_is_not_inherited_by_instances():
    w_class = W_Class('Foo', w_object_class)
    w_obj = _send_new(w_class, [])
    new_id = symbols.intern('new')
    iseq = asm([W_CallInfo(new_id, 0)], 1, 2, [
        insns.GETLOCAL, 0,
        insns.OPT_SEND_WITHOUT_BLOCK, 0,
        insns.LEAVE,
    ])
    frame = Frame(iseq, w_main)
    frame.locals[0] = w_obj
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
    items = [insns.GETLOCAL, 0]
    consts = [W_CallInfo(new_id, len(args_w))]
    for i in range(len(args_w)):
        consts.append(args_w[i])
        items += [insns.PUTOBJECT, i + 1]
    items += [insns.OPT_SEND_WITHOUT_BLOCK, 0, insns.LEAVE]
    iseq = asm(consts, 1, 4 + len(args_w), items)
    frame = Frame(iseq, w_main)
    frame.locals[0] = w_class
    return interp.execute(iseq, frame)


def _main():
    tests = []
    for name in globals().keys():
        if name.startswith('test_'):
            func = globals()[name]
            tests.append((func.__code__.co_firstlineno, name, func))
    tests.sort()
    # A toplevel `def` now mutates the one Object, so undo it between tests.
    baseline = w_object_class.methods.methods.copy()
    for lineno, name, func in tests:
        func()
        w_object_class.methods.methods = baseline.copy()
        w_object_class.method_table_changed()
        print('ok %s' % name)
    print('%d passed' % len(tests))


if __name__ == '__main__':
    import traceback
    try:
        _main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
