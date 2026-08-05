"""Builtin methods, installed on Object."""

import os

import symbols
from methods import W_CFunc
from objects.transparent import w_nil


def write(s):
    os.write(1, s)


class W_Puts(W_CFunc):
    def call(self, w_recv, args_w):
        if len(args_w) == 0:
            write('\n')
        for w_arg in args_w:
            write(w_arg.to_s_str() + '\n')
        return w_nil


def install(w_class):
    mid = symbols.intern('puts')
    w_class.add_method(mid, W_Puts(mid, -1))
