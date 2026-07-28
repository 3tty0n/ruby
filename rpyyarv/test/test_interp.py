import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import insns
import interp
from error import UnsupportedOperation
from frame import Frame
from iseq import W_ISeq
from objects.transparent import W_Fixnum, w_nil, w_true, w_false


def asm(consts, nlocals, stack_max, items):
    """Tiny assembler.

    items is a flat list of ints (opcodes/operands) and strings.  A string
    starting with ':' defines a label at the current offset and takes no
    space; any other string is a forward/backward reference to such a label
    and occupies exactly one slot.
    """
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
    return W_ISeq('<test>', code, consts, nlocals, stack_max)


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
    # untouched local defaults to nil
    iseq2 = asm([], 2, 4, [insns.GETLOCAL, 0, insns.LEAVE])
    assert interp.run(iseq2) is w_nil


def _branchif_taken(w_value):
    # returns True when BRANCHIF jumps
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

    # unknown opcode
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

    # direct Frame check
    frame2 = Frame(iseq)
    w_x = W_Fixnum(1)
    frame2.push(w_x)
    assert frame2.stack[0] is w_x
    assert frame2.pop() is w_x
    assert frame2.stack[0] is None
    assert frame2.sp == 0


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
