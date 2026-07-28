from objects.transparent import W_Fixnum, newbool

# Interface contract C2: wrapped in, wrapped out. Non-Fixnum operands make
# int_w() raise UnsupportedOperation from W_Root. No overflow handling yet.


def w_add(w_a, w_b):
    return W_Fixnum(w_a.int_w() + w_b.int_w())


def w_sub(w_a, w_b):
    return W_Fixnum(w_a.int_w() - w_b.int_w())


def w_mul(w_a, w_b):
    return W_Fixnum(w_a.int_w() * w_b.int_w())


def w_lt(w_a, w_b):
    return newbool(w_a.int_w() < w_b.int_w())


def w_gt(w_a, w_b):
    return newbool(w_a.int_w() > w_b.int_w())


def w_le(w_a, w_b):
    return newbool(w_a.int_w() <= w_b.int_w())


def w_ge(w_a, w_b):
    return newbool(w_a.int_w() >= w_b.int_w())


def w_eq(w_a, w_b):
    return newbool(w_a.int_w() == w_b.int_w())
