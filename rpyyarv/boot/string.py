"""string.c, sprintf.c, pack.c, encoding: String operations."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, VALUEP, INTP, MAX_ARGC,
                                _enter_status, _leave_status, _enter_argv,
                                _leave_argv, _failed, RubyError)


rb_str_len = _ext('rpyyarv_str_len', [VALUE], rffi.LONG)


rb_str_ptr = _ext('rpyyarv_str_ptr', [VALUE], rffi.CCHARP)


rb_str_new = _ext('rpyyarv_str_new', [rffi.CCHARP, rffi.LONG], VALUE,
                  reenters=True)


rb_str_concat = _ext('rpyyarv_str_concat', [rffi.INT, VALUEP], VALUE, reenters=True)


# No reenters: rb_str_eql_internal neither allocates nor raises.
rb_str_eq = _ext('rpyyarv_str_eq', [VALUE, VALUE], VALUE)


rb_str_push = _ext('rpyyarv_str_push', [VALUE, VALUE, INTP], VALUE,
                   reenters=True)


rb_str_start_with = _ext('rpyyarv_str_start_with', [VALUE, VALUE], VALUE)


rb_int_to_s_fast = _ext('rpyyarv_int_to_s', [VALUE], VALUE)


rb_str_casecmp_fast = _ext('rpyyarv_str_casecmp', [VALUE, VALUE], VALUE)


rb_str_cmp_fast = _ext('rpyyarv_str_cmp', [VALUE, VALUE], VALUE)


rb_str_downcase_fast = _ext('rpyyarv_str_downcase', [VALUE], VALUE)


rb_str_downcase_bang = _ext('rpyyarv_str_downcase_bang', [VALUE], VALUE)


rb_str_upcase_fast = _ext('rpyyarv_str_upcase', [VALUE], VALUE)


rb_str_upcase_bang = _ext('rpyyarv_str_upcase_bang', [VALUE], VALUE)


rb_str_dup_fast = _ext('rpyyarv_str_dup', [VALUE], VALUE)


rb_str_length_fast = _ext('rpyyarv_str_length', [VALUE], VALUE)


rb_str_index_of = _ext('rpyyarv_str_index_of', [VALUE, VALUE], VALUE)


rb_str_empty_p = _ext('rpyyarv_str_empty_p', [VALUE], VALUE)


rb_str_uminus = _ext('rpyyarv_str_uminus', [VALUE], VALUE)


rb_str_byteslice2 = _ext('rpyyarv_str_byteslice2', [VALUE, VALUE, VALUE],
                         VALUE)


rb_str_force_encoding_fast = _ext('rpyyarv_str_force_encoding_fast',
                                  [VALUE, VALUE], VALUE, reenters=True)


rb_unpack1_double = _ext('rpyyarv_unpack1_double', [VALUE, VALUE, VALUE],
                         VALUE, reenters=True)


# No reenters: scans and caches a coderange in the flags, allocating nothing.
rb_str_ascii_only_p = _ext('rpyyarv_str_ascii_only_p', [VALUE], VALUE)


rb_pack_double_into = _ext('rpyyarv_pack_double_into', [VALUE, VALUE, VALUE],
                           VALUE, reenters=True)


rb_sprintf_ = _ext('rpyyarv_sprintf', [rffi.INT, VALUEP, VALUE, INTP], VALUE,
                   reenters=True)


rb_cgi_escape_html = _ext('rpyyarv_cgi_escape_html', [VALUE], VALUE)


rb_str_getbyte = _ext('rpyyarv_str_getbyte', [VALUE, VALUE], VALUE)


rb_str_setbyte = _ext('rpyyarv_str_setbyte', [VALUE, VALUE, VALUE], VALUE,
                      reenters=True)


rb_str_append = _ext('rpyyarv_str_append', [VALUE, VALUE], VALUE,
                     reenters=True)


rb_str_ord = _ext('rpyyarv_str_ord', [VALUE], VALUE)


rb_str_char_at = _ext('rpyyarv_str_char_at', [VALUE, VALUE], VALUE)


def str_of(v):
    # rb_string_value_cstr raises on embedded NUL: longjmp past this frame.
    n = rffi.cast(lltype.Signed, rb_str_len(_v(v)))
    if n < 0:
        raise RubyError('to_s')
    return rffi.charpsize2str(rb_str_ptr(_v(v)), n)


def str_concat(parts):
    n = len(parts)
    if n > MAX_ARGC:
        raise RubyError('String#concat')
    with lltype.scoped_alloc(rffi.CArray(VALUE), n + 1) as buf:
        i = 0
        while i < n:
            buf[i] = rffi.cast(VALUE, parts[i])
            i += 1
        return rffi.cast(lltype.Signed,
                         rb_str_concat(rffi.cast(rffi.INT, n), buf))


def str_new(s):
    # Length-carrying, so a literal holding NUL bytes survives the round trip.
    with rffi.scoped_str2charp(s) as c_s:
        return rffi.cast(lltype.Signed, rb_str_new(c_s, len(s)))


def str_getbyte(string, index):
    return rffi.cast(lltype.Signed, rb_str_getbyte(_v(string), _v(index)))


def str_append(string, other):
    """String#<< of String onto String; Qundef when only rb_str_concat can."""
    return rffi.cast(lltype.Signed, rb_str_append(_v(string), _v(other)))


def str_setbyte(string, index, v):
    return rffi.cast(lltype.Signed,
                     rb_str_setbyte(_v(string), _v(index), _v(v)))


def str_ord(string):
    """Unprotected: Qundef unless 7-bit and non-empty."""
    return rffi.cast(lltype.Signed, rb_str_ord(_v(string)))


def str_char_at(string, idx):
    """Unprotected: Qundef unless 7-bit."""
    return rffi.cast(lltype.Signed, rb_str_char_at(_v(string), _v(idx)))


def str_eq(a, b):
    return rffi.cast(lltype.Signed, rb_str_eq(_v(a), _v(b)))


def str_push(string, other):
    """Qundef unless both are Strings."""
    state = _enter_status()
    v = rb_str_push(_v(string), _v(other), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('String#<<')
    return ret


def str_start_with(string, prefix):
    return rffi.cast(lltype.Signed, rb_str_start_with(_v(string), _v(prefix)))


def int_to_s(v):
    return rffi.cast(lltype.Signed, rb_int_to_s_fast(_v(v)))


def str_casecmp(a, b):
    return rffi.cast(lltype.Signed, rb_str_casecmp_fast(_v(a), _v(b)))


def str_cmp(a, b):
    return rffi.cast(lltype.Signed, rb_str_cmp_fast(_v(a), _v(b)))


def str_downcase(s):
    return rffi.cast(lltype.Signed, rb_str_downcase_fast(_v(s)))


def str_downcase_bang(s):
    return rffi.cast(lltype.Signed, rb_str_downcase_bang(_v(s)))


def str_upcase(s):
    return rffi.cast(lltype.Signed, rb_str_upcase_fast(_v(s)))


def str_upcase_bang(s):
    return rffi.cast(lltype.Signed, rb_str_upcase_bang(_v(s)))


def str_dup(v):
    return rffi.cast(lltype.Signed, rb_str_dup_fast(_v(v)))


def str_length(v):
    return rffi.cast(lltype.Signed, rb_str_length_fast(_v(v)))


def str_index_of(s, needle):
    return rffi.cast(lltype.Signed, rb_str_index_of(_v(s), _v(needle)))


def str_format(fmt, args):
    """Kernel#format; the caller keeps len(args) within MAX_ARGC."""
    argc = len(args)
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_sprintf_(rffi.cast(rffi.INT, argc), argv, _v(fmt), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed('format')
    return ret


def cgi_escape_html(s):
    return rffi.cast(lltype.Signed, rb_cgi_escape_html(_v(s)))


def str_empty_p(v):
    return rffi.cast(lltype.Signed, rb_str_empty_p(_v(v)))


def str_uminus(v):
    return rffi.cast(lltype.Signed, rb_str_uminus(_v(v)))


def str_byteslice2(s, beg, length):
    return rffi.cast(lltype.Signed,
                     rb_str_byteslice2(_v(s), _v(beg), _v(length)))


def str_force_encoding_fast(s, enc):
    """Unprotected: Qundef unless the shim knows it cannot raise."""
    return rffi.cast(lltype.Signed, rb_str_force_encoding_fast(_v(s), _v(enc)))


def unpack1_double(s, fmt, offset):
    """Unprotected unpack1: Qundef unless format "E" and 8 bytes in range."""
    return rffi.cast(lltype.Signed,
                     rb_unpack1_double(_v(s), _v(fmt), _v(offset)))


def str_bytesize(v):
    return rffi.cast(lltype.Signed, rb_str_len(_v(v)))


def str_ascii_only_p(v):
    return rffi.cast(lltype.Signed, rb_str_ascii_only_p(_v(v)))


def pack_double_into(ary, fmt, buf):
    """Unprotected pack: Qundef unless format "E" and a writable buffer."""
    return rffi.cast(lltype.Signed,
                     rb_pack_double_into(_v(ary), _v(fmt), _v(buf)))
