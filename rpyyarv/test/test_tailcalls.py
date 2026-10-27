"""Tail calls reuse a frame only after ordinary method/argument checks."""

import pytest

from rpyyarv import debug
from rpyyarv import insns
from rpyyarv import interp
from rpyyarv import iseq
from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.frame import Frame
from rpyyarv.iseq import NO_BLOCK_ISEQ, W_CallInfo
from rpyyarv.methods import W_CFunc, W_ISeqMethod
from rpyyarv.objects.klass import W_Class
from rpyyarv.objects.instance import W_Object
from rpyyarv.objects.transparent import W_Fixnum, w_nil
from rpyyarv.test.support import asm, traced


def countdown(send=insns.OPT_SEND_WITHOUT_BLOCK, indirect=False,
              result_slot=1):
    mid = symbols.intern('countdown')
    items = [
        insns.GETLOCAL, 0, 0, insns.PUTOBJECT, 0, insns.OPT_EQ,
        insns.BRANCHUNLESS, 'again',
        insns.GETLOCAL, result_slot, 0, insns.LEAVE,
        ':again', insns.PUTSELF,
        insns.GETLOCAL, 0, 0, insns.PUTOBJECT, 1, insns.OPT_MINUS,
        insns.GETLOCAL, 2, 0, insns.GETLOCAL, 1, 0,
        send, 2,
    ]
    if send == insns.SEND:
        items.append(NO_BLOCK_ISEQ)
    if indirect:
        items += [insns.JUMP, 'return', ':return', insns.NOP]
    items.append(insns.LEAVE)
    body = asm([W_Fixnum(0), W_Fixnum(1), W_CallInfo(mid, 3)],
               4, 5, items, name='countdown', nparams=3)
    klass = W_Class('Counter')
    klass.add_method(mid, W_ISeqMethod(mid, body))
    return body, W_Object(klass)


def new_frame(body, recv, n):
    frame = Frame(body, recv)
    frame.setlocal(0, W_Fixnum(n))
    frame.setlocal(1, W_Fixnum(11))
    frame.setlocal(2, W_Fixnum(22))
    frame.setlocal(3, W_Fixnum(99))
    return frame


def count_allocations(monkeypatch):
    allocated = []

    class CountingFrame(Frame):
        def __init__(self, iseq, w_self):
            Frame.__init__(self, iseq, w_self)
            allocated.append(self)

    monkeypatch.setattr(interp, 'Frame', CountingFrame)
    return allocated


@pytest.mark.parametrize('send', [insns.OPT_SEND_WITHOUT_BLOCK, insns.SEND])
@pytest.mark.parametrize('indirect', [False, True])
def test_deep_tail_recursion_swaps_arguments_without_allocating(
        monkeypatch, send, indirect):
    body, recv = countdown(send, indirect)
    frame = new_frame(body, recv, 5001)
    allocated = count_allocations(monkeypatch)
    assert interp.execute(body, frame).int_w() == 22
    assert allocated == []
    assert frame.sp == body.nlocals
    assert all(frame.peek(body.nlocals + i) is None
               for i in range(body.stack_max))
    assert frame.getlocal(3) is w_nil


def test_tail_call_resets_non_argument_locals():
    body, recv = countdown(result_slot=3)
    assert interp.execute(body, new_frame(body, recv, 1)) is w_nil


def test_debug_keeps_recursive_call_events(monkeypatch):
    body, recv = countdown()
    allocated = count_allocations(monkeypatch)
    text = traced('call', lambda: interp.execute(body, new_frame(body, recv, 3)))
    assert text.count('-> countdown(') == 3
    assert text.count('<- countdown =') == 3
    assert len(allocated) == 3
    assert debug.state.depth == 0


def test_tail_call_still_checks_arity():
    body, recv = countdown()
    body.nparams = 2
    with pytest.raises(UnsupportedOperation) as info:
        interp.execute(body, new_frame(body, recv, 1))
    assert 'wrong number of arguments' in info.value.msg


def test_lookup_uses_actual_method_after_redefinition(monkeypatch):
    mid = symbols.intern('replace_me')
    replace_id = symbols.intern('replace')
    replacement = asm([W_Fixnum(42)], 0, 1,
                      [insns.PUTOBJECT, 0, insns.LEAVE])
    klass = W_Class('Redefined')

    class Replace(W_CFunc):
        def call(self, w_recv, args_w, w_block):
            klass.add_method(mid, W_ISeqMethod(mid, replacement))
            return w_nil

    klass.add_method(replace_id, Replace(replace_id, 0))
    body = asm([W_CallInfo(replace_id, 0), W_CallInfo(mid, 0)], 0, 1, [
        insns.PUTSELF, insns.OPT_SEND_WITHOUT_BLOCK, 0, insns.POP,
        insns.PUTSELF, insns.OPT_SEND_WITHOUT_BLOCK, 1, insns.LEAVE,
    ])
    klass.add_method(mid, W_ISeqMethod(mid, body))
    allocated = count_allocations(monkeypatch)
    assert interp.execute(body, Frame(body, W_Object(klass))).int_w() == 42
    assert len(allocated) == 1


def test_tail_call_updates_self(monkeypatch):
    mid = symbols.intern('switch_self')
    klass = W_Class('Receiver')
    other = W_Object(klass)
    body = asm([W_Fixnum(0), W_CallInfo(mid, 1), other], 1, 2, [
        insns.GETLOCAL, 0, 0, insns.BRANCHUNLESS, 'again',
        insns.PUTSELF, insns.LEAVE,
        ':again', insns.PUTOBJECT, 2, insns.PUTOBJECT, 0,
        insns.OPT_SEND_WITHOUT_BLOCK, 1, insns.LEAVE,
    ], nparams=1)
    klass.add_method(mid, W_ISeqMethod(mid, body))
    frame = Frame(body, W_Object(klass))
    allocated = count_allocations(monkeypatch)
    assert interp.execute(body, frame) is other
    assert allocated == []


def test_tail_position_rejects_work_and_cycles():
    body = asm([], 0, 1, [insns.JUMP, 0, insns.LEAVE])
    assert not iseq.tail_position(body.code, 0)
    assert iseq.tail_position(body.code, 2)
    assert not iseq.tail_position(body.code, 3)
    body = asm([], 0, 1, [insns.NOP, insns.OPT_PLUS, insns.LEAVE])
    assert not iseq.tail_position(body.code, 0)


def test_ackermann_preserves_the_nested_non_tail_call(monkeypatch):
    mid = symbols.intern('ack')
    body = asm([W_Fixnum(0), W_Fixnum(1), W_CallInfo(mid, 2)], 2, 6, [
        insns.GETLOCAL, 0, 0, insns.PUTOBJECT, 0, insns.OPT_EQ,
        insns.BRANCHUNLESS, 'nonzero_m',
        insns.GETLOCAL, 1, 0, insns.PUTOBJECT, 1, insns.OPT_PLUS, insns.LEAVE,
        ':nonzero_m', insns.GETLOCAL, 1, 0, insns.PUTOBJECT, 0, insns.OPT_EQ,
        insns.BRANCHUNLESS, 'nested',
        insns.PUTSELF, insns.GETLOCAL, 0, 0, insns.PUTOBJECT, 1,
        insns.OPT_MINUS,
        insns.PUTOBJECT, 1, insns.OPT_SEND_WITHOUT_BLOCK, 2, insns.LEAVE,
        ':nested', insns.PUTSELF,
        insns.GETLOCAL, 0, 0, insns.PUTOBJECT, 1, insns.OPT_MINUS,
        insns.PUTSELF, insns.GETLOCAL, 0, 0,
        insns.GETLOCAL, 1, 0, insns.PUTOBJECT, 1, insns.OPT_MINUS,
        insns.OPT_SEND_WITHOUT_BLOCK, 2,
        insns.OPT_SEND_WITHOUT_BLOCK, 2, insns.LEAVE,
    ], name='ack', nparams=2)
    klass = W_Class('Ackermann')
    klass.add_method(mid, W_ISeqMethod(mid, body))
    frame = Frame(body, W_Object(klass))
    frame.setlocal(0, W_Fixnum(3))
    frame.setlocal(1, W_Fixnum(4))
    allocated = count_allocations(monkeypatch)
    assert interp.execute(body, frame).int_w() == 125
    assert allocated  # The inner call still needs its own frame.
