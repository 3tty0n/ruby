"""ctypes check of the same boot_shim.c that boot.py drives through rffi.

Runs only when `make link` has built the shim. rpyyarv_boot() starts an
embedded CRuby that cannot be torn down and restarted, so this module boots
exactly once, for one test.
"""

import ctypes
import os

import pytest

import to_a_layout

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)

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
                try:
                    fn = getattr(lib, name)
                except AttributeError:
                    pytest.skip("%s has no %s; rerun `make link`"
                                % (os.path.basename(path), name))
                fn.argtypes = argtypes
                fn.restype = restype
            return lib
    pytest.skip("librpyyarv_boot not built; run `make link` first")


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


@pytest.fixture(scope='module')
def booted():
    """(lib, call0, iseq_to_a, script) for the <main> ISeq of fib.rb."""
    script = os.path.join(HERE, 'fib.rb')
    lib = load_shim()
    args = [b"rpyyarv", script.encode()]
    argv_arr = (ctypes.c_char_p * (len(args) + 1))(*(args + [None]))
    status = ctypes.c_int(0)

    node = lib.rpyyarv_boot(len(args), argv_arr, ctypes.byref(status))
    assert node, "no executable node (status=%d)" % status.value

    iseqw = lib.rpyyarv_iseqw_new(node)
    state = ctypes.c_int(0)

    def call0(recv, mid):
        v = lib.rpyyarv_call0(recv, mid.encode(), ctypes.byref(state))
        assert not state.value, "Ruby exception in %s" % mid
        return v

    yield lib, call0, call0(iseqw, "to_a"), script
    lib.rpyyarv_cleanup(0)


def test_boot_intercepts_the_main_iseq(booted):
    lib, _, ary, _ = booted
    assert lib.rpyyarv_is_array(ary)
    # ruby_options yields ISEQ_TYPE_MAIN where compile_file yields :top
    assert sym(lib, lib.rpyyarv_ary_entry(ary, to_a_layout.I_TYPE)) \
        in ("top", "main")


def test_front_end_helpers(booted):
    """The shim calls bootiseq.py makes, exercised without RPython."""
    lib, call0, ary, script = booted
    check_frontend_helpers(lib, call0, ary, script)
