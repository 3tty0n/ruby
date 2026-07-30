import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import insns
import interp
import symbols
from error import UnsupportedOperation
from frame import Frame
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from methods import W_Method
from objects.main import W_Main, w_main
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
    assert w_self.methods.lookup(add_id) is None
    frame = Frame(iseq, w_self)
    assert interp.execute(iseq, frame).int_w() == 7
    w_method = w_self.methods.lookup(add_id)
    assert isinstance(w_method, W_Method)
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
