"""Unit tests for the object model: wrapping, classes, method lookup.

Nothing here runs an ISeq -- objects are tested straight through their own
interface, which is the cheapest way to pin down new behaviour.
"""

import pytest

import symbols
from error import UnsupportedOperation
from methods import MethodTable, W_CFunc, W_Method
from objects.array import W_Array
from objects.instance import W_Object
from objects.main import W_Main
from objects.string import W_String
from objects.transparent import (W_Fixnum, newbool, w_false, w_nil, w_true)

from objects.klass import (W_Class, w_array_class, w_class_class,
                           w_integer_class, w_object_class, w_regexp_class,
                           w_string_class)
from objects.regexp import W_Regexp

def test_only_nil_and_false_are_falsy():
    assert not w_nil.is_true()
    assert not w_false.is_true()
    for w_x in (w_true, W_Fixnum(0), W_String(''), W_Array([])):
        assert w_x.is_true(), w_x.repr()


def test_newbool_interns():
    assert newbool(True) is w_true
    assert newbool(False) is w_false


def test_unwrapping_is_typed():
    assert W_Fixnum(3).int_w() == 3
    assert W_String('hi').str_w() == 'hi'
    with pytest.raises(UnsupportedOperation):
        W_String('hi').int_w()
    with pytest.raises(UnsupportedOperation):
        W_Fixnum(3).str_w()


def test_to_s_str():
    assert W_Fixnum(-7).to_s_str() == '-7'
    assert W_String('hi').to_s_str() == 'hi'
    assert w_nil.to_s_str() == ''
    assert w_true.to_s_str() == 'true'
    with pytest.raises(UnsupportedOperation):
        W_Array([]).to_s_str()


def test_getclass():
    assert W_Fixnum(1).getclass() is w_integer_class
    assert W_String('').getclass() is w_string_class
    assert W_Array([]).getclass() is w_array_class
    assert W_Class('C').getclass() is w_class_class
    assert W_Main().getclass() is w_object_class
    assert W_Regexp('x').getclass() is w_regexp_class


def test_lookup_walks_superclasses():
    mid = symbols.intern('inherited_probe')
    w_base = W_Class('Base', w_object_class)
    w_derived = W_Class('Derived', w_base)
    w_method = W_Method(mid)
    w_base.add_method(mid, w_method)
    assert W_Object(w_derived).lookup_method(mid) is w_method


def test_lookup_prefers_the_nearest_definition():
    mid = symbols.intern('overridden_probe')
    w_base = W_Class('Base', w_object_class)
    w_derived = W_Class('Derived', w_base)
    w_base.add_method(mid, W_Method(mid))
    w_own = W_Method(mid)
    w_derived.add_method(mid, w_own)
    assert w_derived.find_method(mid) is w_own


def test_a_later_definition_invalidates_the_cached_answer():
    """add_method bumps the version the elidable lookup is keyed on."""
    mid = symbols.intern('late_probe')
    w_base = W_Class('Base', w_object_class)
    w_derived = W_Class('Derived', w_base)
    assert w_derived.find_method(mid) is None
    w_method = W_Method(mid)
    w_base.add_method(mid, w_method)
    assert w_derived.find_method(mid) is w_method


def test_missing_method_names_the_receiver():
    mid = symbols.intern('nope_probe')
    with pytest.raises(UnsupportedOperation) as e:
        W_Fixnum(1).lookup_method(mid)
    assert e.value.msg == "undefined method 'nope_probe' for 1"


def test_a_toplevel_def_lands_on_object():
    mid = symbols.intern('toplevel_probe')
    w_main = W_Main()
    assert w_main.defines_private()
    w_method = W_Method(mid, private=True)
    w_main.define_method(mid, w_method)
    assert w_object_class.find_method(mid) is w_method


def test_most_objects_cannot_hold_a_method():
    with pytest.raises(UnsupportedOperation):
        W_Fixnum(1).define_method(symbols.intern('x'), W_Method(0))


def test_symbols_are_interned():
    assert symbols.intern('same_probe') == symbols.intern('same_probe')
    assert symbols.name_of(symbols.intern('named_probe')) == 'named_probe'
    assert symbols.name_of(1 << 30) == '<id 1073741824>'


def test_method_table_is_a_plain_map():
    table = MethodTable()
    mid = symbols.intern('table_probe')
    assert table.lookup(mid) is None
    w_method = W_Method(mid)
    table.define(mid, w_method)
    assert table.lookup(mid) is w_method


def test_a_cfunc_without_a_body_says_so():
    mid = symbols.intern('bodyless_probe')
    with pytest.raises(UnsupportedOperation) as e:
        W_CFunc(mid, 0).call(w_nil, [])
    assert e.value.msg == "'bodyless_probe' has no body"


def test_repr_is_for_error_messages():
    assert W_Fixnum(2).repr() == '2'
    assert W_String('hi').repr() == '"hi"'
    assert W_Class('C').repr() == 'C'
    assert W_Object(W_Class('C')).repr() == '#<C>'
    assert W_Main().repr() == 'main'
    assert W_Regexp('foo').repr() == '/foo/'
