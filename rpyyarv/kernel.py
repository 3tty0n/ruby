"""Builtin methods, installed on Object."""

import os

import symbols
from methods import W_CFunc
from objects.string import W_String 
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

class W_ToS(W_CFunc):
    def call(self, w_recv, args_w):
        return W_String(w_recv.to_s_str())

def install(w_class):
    puts_id = symbols.intern('puts')
    w_class.add_method(puts_id, W_Puts(puts_id, -1))
    to_s_id = symbols.intern('to_s')
    w_class.add_method(to_s_id, W_ToS(to_s_id, 0))
