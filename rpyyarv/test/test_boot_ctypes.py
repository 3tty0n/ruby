"""ctypes check of the same boot_shim.c that boot.py drives through rffi."""

from __future__ import print_function

import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
TOP = os.path.dirname(PROJ)
BUILD = os.environ.get("RPYYARV_BUILD", os.path.join(TOP, "build"))

if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

import to_a_layout

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
    "rpyyarv_is_string": ([VALUE], ctypes.c_int),
    "rpyyarv_is_hash": ([VALUE], ctypes.c_int),
    "rpyyarv_is_nil": ([VALUE], ctypes.c_int),
    "rpyyarv_is_true": ([VALUE], ctypes.c_int),
    "rpyyarv_is_false": ([VALUE], ctypes.c_int),
    "rpyyarv_num2long": ([VALUE], ctypes.c_long),
    "rpyyarv_hash_aref": ([VALUE, ctypes.c_char_p], VALUE),
    "rpyyarv_sym_cstr": ([VALUE], ctypes.c_char_p),
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


def sym(lib, v):
    return lib.rpyyarv_sym_cstr(v).decode()


def kind_of(lib, v):
    if lib.rpyyarv_is_fixnum(v):
        return to_a_layout.K_INTEGER
    if lib.rpyyarv_is_string(v):
        return to_a_layout.K_STRING
    if lib.rpyyarv_is_symbol(v):
        return to_a_layout.K_SYMBOL
    if lib.rpyyarv_is_array(v):
        return to_a_layout.K_ARRAY
    if lib.rpyyarv_is_hash(v):
        return to_a_layout.K_HASH
    return "?"


def check_layout(lib, ary, what):
    """The table bootiseq.py trusts, against a real iseq."""
    n = lib.rpyyarv_ary_len(ary)
    assert n == to_a_layout.LENGTH, \
        "%s: to_a has %d elements, expected %d" % (what, n, to_a_layout.LENGTH)
    for index, kind in to_a_layout.EXPECTED:
        found = kind_of(lib, lib.rpyyarv_ary_entry(ary, index))
        assert found == kind, \
            "%s: to_a[%d] holds %s, expected %s" % (what, index, found, kind)
    magic = lib.rpyyarv_cstr(
        lib.rpyyarv_ary_entry(ary, to_a_layout.I_MAGIC)).decode()
    assert magic == to_a_layout.MAGIC, "%s: to_a[0] is %r" % (what, magic)


def insns_of(lib, ary):
    found = {}
    body = lib.rpyyarv_ary_entry(ary, to_a_layout.I_BODY)
    for i in range(lib.rpyyarv_ary_len(body)):
        e = lib.rpyyarv_ary_entry(body, i)
        if lib.rpyyarv_is_array(e):
            found[sym(lib, lib.rpyyarv_ary_entry(e, 0))] = e
    return found


def params_of(lib, call0, ary):
    """(lead_num, extra keys) exactly as bootiseq._extra_params computes it."""
    params = lib.rpyyarv_ary_entry(ary, to_a_layout.I_PARAMS)
    lead = lib.rpyyarv_hash_aref(params, b"lead_num")
    keys = call0(params, "keys")
    names = []
    for i in range(lib.rpyyarv_ary_len(keys)):
        name = sym(lib, lib.rpyyarv_ary_entry(keys, i))
        if name != "lead_num":
            names.append(name)
    return (0 if lib.rpyyarv_is_nil(lead) else lib.rpyyarv_num2long(lead),
            ",".join(names))


def dumped_params(path):
    rows = []
    with open(path) as f:
        for line in f:
            fields = line.rstrip("\n").split("\t")
            if fields[0] == "params":
                rows.append((int(fields[1]), fields[2] if len(fields) > 2
                             else ""))
    return rows


def check_frontend_helpers(lib, call0, ary, script):
    """The shim calls bootiseq.py makes, exercised without RPython."""
    check_layout(lib, ary, "<main>")

    misc = lib.rpyyarv_ary_entry(ary, to_a_layout.I_MISC)
    assert lib.rpyyarv_num2long(
        lib.rpyyarv_hash_aref(misc, b"stack_max")) > 0, "misc[:stack_max]"
    assert lib.rpyyarv_is_nil(lib.rpyyarv_hash_aref(misc, b"nope"))
    # ruby_options yields ISEQ_TYPE_MAIN where compile_file yields :top
    assert sym(lib, lib.rpyyarv_ary_entry(ary, to_a_layout.I_TYPE)) \
        in ("top", "main")

    seen = insns_of(lib, ary)
    assert "definemethod" in seen, "definemethod in <main>"
    assert sym(lib, lib.rpyyarv_ary_entry(seen["definemethod"], 1)) == "fib"

    nested = lib.rpyyarv_ary_entry(seen["definemethod"], 2)
    check_layout(lib, nested, "fib")

    cd = lib.rpyyarv_ary_entry(seen["opt_send_without_block"], 1)
    assert lib.rpyyarv_is_hash(cd), "call data is a Hash"
    assert sym(lib, lib.rpyyarv_hash_aref(cd, b"mid")) in ("fib", "puts")
    assert lib.rpyyarv_num2long(lib.rpyyarv_hash_aref(cd, b"orig_argc")) == 1
    assert lib.rpyyarv_is_nil(lib.rpyyarv_hash_aref(cd, b"kw_arg"))

    lit = lib.rpyyarv_ary_entry(seen["putobject"], 1)
    assert lib.rpyyarv_is_string(lit) or lib.rpyyarv_is_fixnum(lit) \
        or lib.rpyyarv_is_array(lit)

    try:
        check_layout(lib, lib.rpyyarv_ary_entry(ary, to_a_layout.I_BODY),
                     "body")
    except AssertionError:
        pass
    else:
        raise AssertionError("check_layout accepted a non-iseq array")

    # Both front ends must judge simple-params the same way.
    dump = os.path.splitext(script)[0] + ".iseq"
    if os.path.exists(dump):
        booted = [params_of(lib, call0, ary), params_of(lib, call0, nested)]
        assert booted == dumped_params(dump), \
            "params disagree: booted %r, dumped %r" % (booted,
                                                       dumped_params(dump))
    print("[rpyyarv] front-end helpers: ok")


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

    check_frontend_helpers(lib, call0, ary, script)

    print("[rpyyarv] ruby_run_node() was never called.")
    return lib.rpyyarv_cleanup(0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
