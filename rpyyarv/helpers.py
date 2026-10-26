from rpyyarv.objects.float import W_Float
from rpyyarv.objects.string import W_String
from rpyyarv.objects.transparent import newbool, newint

# Interface contract C2: wrapped in, wrapped out. A Float operand makes both
# sides Floats, as in CRuby; other non-integer operands make int_w() raise
# UnsupportedOperation from W_Root. No overflow handling yet.
# TODO: CRuby compares an Integer with a Float exactly; float() rounds
# integers beyond 2**53, so 2**53 + 1 == 2.0**53 is true here.


def _floats(w_a, w_b):
    return isinstance(w_a, W_Float) or isinstance(w_b, W_Float)


def w_add(w_a, w_b):
    if isinstance(w_a, W_String) and isinstance(w_b, W_String):
        return W_String(w_a.str_w() + w_b.str_w())
    if _floats(w_a, w_b):
        return W_Float(w_a.float_w() + w_b.float_w())
    return newint(w_a.int_w() + w_b.int_w())

def w_sub(w_a, w_b):
    if _floats(w_a, w_b):
        return W_Float(w_a.float_w() - w_b.float_w())
    return newint(w_a.int_w() - w_b.int_w())


def w_mul(w_a, w_b):
    if _floats(w_a, w_b):
        return W_Float(w_a.float_w() * w_b.float_w())
    return newint(w_a.int_w() * w_b.int_w())


def w_lt(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(w_a.float_w() < w_b.float_w())
    return newbool(w_a.int_w() < w_b.int_w())


def w_gt(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(w_a.float_w() > w_b.float_w())
    return newbool(w_a.int_w() > w_b.int_w())


def w_le(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(w_a.float_w() <= w_b.float_w())
    return newbool(w_a.int_w() <= w_b.int_w())


def w_ge(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(w_a.float_w() >= w_b.float_w())
    return newbool(w_a.int_w() >= w_b.int_w())


def w_eq(w_a, w_b):
    if _floats(w_a, w_b):
        return newbool(w_a.float_w() == w_b.float_w())
    return newbool(w_a.int_w() == w_b.int_w())
