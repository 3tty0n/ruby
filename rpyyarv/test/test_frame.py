import pytest

from frame import Frame
from objects.transparent import W_Fixnum, w_nil
from support import asm


@pytest.mark.parametrize('nlocals, stack_max', [
    (0, 0), (0, 8), (2, 6), (7, 3), (8, 1), (10, 4),
])
def test_inline_and_overflow_slots_do_not_alias(nlocals, stack_max):
    body = asm([], nlocals, stack_max, [])
    frame = Frame(body)
    other = Frame(body)
    assert len(frame.extra) == max(0, nlocals + stack_max - 8)
    assert all(frame.getlocal(i) is w_nil for i in range(nlocals))
    assert all(frame.peek(nlocals + i) is None for i in range(stack_max))
    for i in range(nlocals):
        frame.setlocal(i, W_Fixnum(i))
    for i in range(stack_max):
        frame.push(W_Fixnum(100 + i))
    assert [frame.getlocal(i).int_w() for i in range(nlocals)] == list(range(nlocals))
    for i in reversed(range(stack_max)):
        assert frame.pop().int_w() == 100 + i
        assert frame.peek(nlocals + i) is None
    assert all(other.getlocal(i) is w_nil for i in range(nlocals))
    assert all(other.peek(nlocals + i) is None for i in range(stack_max))
    assert frame.sp == nlocals
