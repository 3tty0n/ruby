"""ctypes check of the same boot_shim.c that boot.py drives through rffi.

Runs without the RPython toolchain, so a failure here points at CRuby or the
FFI boundary rather than at RPython.
"""

from __future__ import print_function

import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
TOP = os.path.dirname(PROJ)
BUILD = os.environ.get("RPYYARV_BUILD", os.path.join(TOP, "build"))

VALUE = ctypes.c_size_t
INTP = ctypes.POINTER(ctypes.c_int)

SIGNATURES = {
    "rpyyarv_boot": ([ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), INTP],
                     ctypes.c_void_p),
    "rpyyarv_cleanup": ([ctypes.c_int], ctypes.c_int),
    "rpyyarv_iseqw_new": ([ctypes.c_void_p], VALUE),
    "rpyyarv_call0": ([VALUE, ctypes.c_char_p, INTP], VALUE),
    "rpyyarv_cstr": ([VALUE], ctypes.c_char_p),
    "rpyyarv_inspect_cstr": ([VALUE], ctypes.c_char_p),
    "rpyyarv_ary_len": ([VALUE], ctypes.c_long),
    "rpyyarv_ary_entry": ([VALUE, ctypes.c_long], VALUE),
    "rpyyarv_is_array": ([VALUE], ctypes.c_int),
    "rpyyarv_is_symbol": ([VALUE], ctypes.c_int),
    "rpyyarv_is_fixnum": ([VALUE], ctypes.c_int),
}


def load_shim():
    for ext in ("dylib", "so"):
        path = os.path.join(PROJ, "librpyyarv_boot." + ext)
        if os.path.exists(path):
            lib = ctypes.CDLL(path)
            for name, (argtypes, restype) in SIGNATURES.items():
                fn = getattr(lib, name)
                fn.argtypes = argtypes
                fn.restype = restype
            return lib
    sys.exit("librpyyarv_boot not found; run `make shim` first")


def main(argv):
    script = argv[1] if len(argv) > 1 else os.path.join(HERE, "fib.rb")
    lib = load_shim()

    args = [b"rpyyarv", script.encode() if str is not bytes else script]
    argv_arr = (ctypes.c_char_p * (len(args) + 1))(*(args + [None]))
    status = ctypes.c_int(0)

    n = lib.rpyyarv_boot(len(args), argv_arr, ctypes.byref(status))
    if not n:
        print("[rpyyarv] no executable node (status=%d)" % status.value)
        return status.value

    print("[rpyyarv] === Success: intercepted main ISeq ===")
    iseqw = lib.rpyyarv_iseqw_new(n)
    state = ctypes.c_int(0)

    def call0(recv, mid):
        v = lib.rpyyarv_call0(recv, mid.encode(), ctypes.byref(state))
        if state.value:
            raise RuntimeError("Ruby exception in %s" % mid)
        return v

    def show(v):
        s = lib.rpyyarv_inspect_cstr(v)
        return s.decode("utf-8", "replace") if s else "<inspect failed>"

    print("[rpyyarv] label         : %s" % show(call0(iseqw, "label")))
    print("[rpyyarv] absolute_path : %s" % show(call0(iseqw, "absolute_path")))

    ary = call0(iseqw, "to_a")
    print("[rpyyarv] to_a.size     : %d" % lib.rpyyarv_ary_len(ary))

    insns = lib.rpyyarv_ary_entry(ary, lib.rpyyarv_ary_len(ary) - 1)
    n_elem = lib.rpyyarv_ary_len(insns)
    n_insn = n_label = n_lineno = 0
    for i in range(n_elem):
        e = lib.rpyyarv_ary_entry(insns, i)
        if lib.rpyyarv_is_array(e):
            n_insn += 1
        elif lib.rpyyarv_is_symbol(e):
            n_label += 1
        elif lib.rpyyarv_is_fixnum(e):
            n_lineno += 1
    print("[rpyyarv] elements: %d (insn %d / label %d / lineno %d)"
          % (n_elem, n_insn, n_label, n_lineno))

    shown = 0
    for i in range(n_elem):
        if shown >= 6:
            break
        e = lib.rpyyarv_ary_entry(insns, i)
        if not lib.rpyyarv_is_array(e):
            continue
        s = show(e)
        print("[rpyyarv]   %s" % (s[:100] + ("..." if len(s) > 100 else "")))
        shown += 1

    print("[rpyyarv] ruby_run_node() was never called.")
    return lib.rpyyarv_cleanup(0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
