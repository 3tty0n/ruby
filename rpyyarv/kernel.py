"""Builtin methods, installed on Object."""

import os

from rpyyarv import symbols
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.string import W_String 
from rpyyarv.objects.transparent import W_Fixnum, w_nil
from rpyyarv.rlib import now_ns


def write(s):
    os.write(1, s)


class W_Puts(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        if len(args_w) == 0:
            write('\n')
        for w_arg in args_w:
            write(w_arg.to_s_str() + '\n')
        return w_nil

class W_ToS(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return W_String(w_recv.to_s_str())

class W_BenchNowNs(W_CFunc):
    """Monotonic clock in integer nanoseconds, for the benchmark harness."""
    def call(self, w_recv, args_w, w_block):
        return W_Fixnum(now_ns())

def install(w_class):
    puts_id = symbols.intern('puts')
    w_class.add_method(puts_id, W_Puts(puts_id, -1))
    to_s_id = symbols.intern('to_s')
    w_class.add_method(to_s_id, W_ToS(to_s_id, 0))
    now_id = symbols.intern('bench_now_ns')
    w_class.add_method(now_id, W_BenchNowNs(now_id, 0))
