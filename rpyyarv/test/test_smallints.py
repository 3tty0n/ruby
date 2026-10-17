"""Immediate integers retain a boxed fallback at both tag boundaries."""

import sys

import pytest

import helpers
from objects import transparent
from objects.klass import w_integer_class
from objects.transparent import W_Fixnum, W_SmallFixnum, newint


LIMIT = sys.maxsize >> 1


@pytest.fixture(autouse=True)
def enable_immediate_integers(monkeypatch):
    monkeypatch.setattr(transparent, 'tagged_ints_enabled', lambda: True)


@pytest.mark.parametrize('value', [0, 1, -1, LIMIT, -LIMIT - 1,
                                 LIMIT + 1, -LIMIT - 2,
                                 sys.maxsize, -sys.maxsize - 1])
def test_integer_representation_preserves_value(value):
    w_value = newint(value)
    expected = W_SmallFixnum if -LIMIT - 1 <= value <= LIMIT else W_Fixnum
    assert isinstance(w_value, expected)
    assert w_value.int_w() == value
    assert w_value.get_intval() == value
    assert w_value.getclass() is w_integer_class
    assert w_value.to_s_str() == str(value)
    assert w_value.repr() == str(value)
    assert w_value.is_true()  # Ruby's zero is truthy too.


def test_arithmetic_crosses_tag_boundaries_in_both_directions():
    high = helpers.w_add(newint(LIMIT), newint(1))
    low = helpers.w_sub(newint(-LIMIT - 1), newint(1))
    assert isinstance(high, W_Fixnum) and high.int_w() == LIMIT + 1
    assert isinstance(low, W_Fixnum) and low.int_w() == -LIMIT - 2
    assert isinstance(helpers.w_sub(high, newint(1)), W_SmallFixnum)
    assert isinstance(helpers.w_add(low, newint(1)), W_SmallFixnum)
    assert helpers.w_mul(newint(LIMIT), newint(2)).int_w() == LIMIT * 2


def test_default_boxing_can_be_selected_without_changing_values(monkeypatch):
    monkeypatch.setattr(transparent, 'tagged_ints_enabled', lambda: False)
    assert isinstance(newint(1), W_Fixnum)
    assert helpers.w_add(newint(1), newint(2)).int_w() == 3
