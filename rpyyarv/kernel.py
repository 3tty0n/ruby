"""Builtin methods, installed on Object."""

import os

import symbols
from methods import W_CFunc
from objects.string import W_String
from objects.transparent import newint, w_nil
from rlib import now_ns


def write(s):
    os.write(1, s)


class W_Puts(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        import interp
        if len(args_w) == 0:
            write('\n')
        for w_arg in args_w:
            s = interp.to_s_string(w_arg).str_w()
            if not s.endswith('\n'):   # CRuby adds a newline only if missing
                s += '\n'
            write(s)
        return w_nil

class W_ToS(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        return W_String(w_recv.to_s_str())

class W_BenchNowNs(W_CFunc):
    """Monotonic clock in integer nanoseconds, for the benchmark harness."""
    def call(self, w_recv, args_w, w_block):
        return newint(now_ns())

def install_to_s(w_class):
    to_s_id = symbols.intern('to_s')
    w_class.add_method(to_s_id, W_ToS(to_s_id, 0))

def install(w_class):
    puts_id = symbols.intern('puts')
    w_class.add_method(puts_id, W_Puts(puts_id, -1, True))  # Kernel#puts is private
    to_s_id = symbols.intern('to_s')
    w_class.add_method(to_s_id, W_ToS(to_s_id, 0))
    now_id = symbols.intern('bench_now_ns')
    w_class.add_method(now_id, W_BenchNowNs(now_id, 0))
