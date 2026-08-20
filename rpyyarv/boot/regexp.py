"""re.c + strscan.c: Regexp, MatchData, and StringScanner."""
from __future__ import absolute_import

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, VALUEP, INTP, MAX_ARGC,
                                _enter_status, _leave_status, _enter_argv,
                                _leave_argv, _failed, _failed_mid, RubyError)


rb_getspecial = _ext('rpyyarv_getspecial', [rffi.INT, INTP], VALUE,
                     reenters=True)


rb_toregexp = _ext('rpyyarv_toregexp',
                   [rffi.INT, rffi.INT, VALUEP, INTP], VALUE,
                   reenters=True)


rb_str_gsub2 = _ext('rpyyarv_str_gsub2', [VALUE, VALUE, VALUE, VALUE, INTP],
                    VALUE, reenters=True)


rb_str_tr1 = _ext('rpyyarv_str_tr1', [VALUE, VALUE, VALUE], VALUE)


rb_str_match_p = _ext('rpyyarv_str_match_p', [VALUE, VALUE, INTP], VALUE,
                      reenters=True)


rb_str_eq_tilde = _ext('rpyyarv_str_eq_tilde', [VALUE, VALUE, INTP], VALUE,
                       reenters=True)


rb_reg_eqq_fast = _ext('rpyyarv_reg_eqq', [VALUE, VALUE, INTP], VALUE,
                       reenters=True)


rb_last_match0 = _ext('rpyyarv_last_match0', [], VALUE)


rb_last_match1 = _ext('rpyyarv_last_match1', [VALUE], VALUE)


rb_str_match_fast = _ext('rpyyarv_str_match', [VALUE, VALUE, INTP], VALUE,
                         reenters=True)


rb_ss_pos = _ext('rpyyarv_ss_pos', [VALUE], VALUE)


rb_ss_set_pos = _ext('rpyyarv_ss_set_pos', [VALUE, VALUE], VALUE)


rb_ss_eos_p = _ext('rpyyarv_ss_eos_p', [VALUE], VALUE)


rb_ss_matched_size = _ext('rpyyarv_ss_matched_size', [VALUE], VALUE)


rb_ss_skip = _ext('rpyyarv_ss_skip', [VALUE, VALUE, INTP], VALUE,
                  reenters=True)


rb_str_match_p_fast = _ext('rpyyarv_str_match_p_fast', [VALUE, VALUE], VALUE)


def getspecial(type):
    state = _enter_status()
    v = rb_getspecial(rffi.cast(rffi.INT, type), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('$~')
    return ret


def toregexp(opt, parts):
    n = len(parts)
    if n > MAX_ARGC:
        raise RubyError('toregexp')
    buf = _enter_argv(n)
    i = 0
    while i < n:
        buf[i] = rffi.cast(VALUE, parts[i])
        i += 1
    state = _enter_status()
    out = rb_toregexp(rffi.cast(rffi.INT, opt), rffi.cast(rffi.INT, n),
                      buf, state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, out)
    _leave_argv(buf)
    if failed:
        _failed('toregexp')
    return ret


def str_gsub2(recv, pat, rep, rid, mid):
    """gsub/gsub! of a Regexp|String pattern, backref-free replacement."""
    state = _enter_status()
    v = rb_str_gsub2(_v(recv), _v(pat), _v(rep), rffi.cast(VALUE, rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed_mid(mid)
    return ret


def str_eq_tilde(a, b):
    """String =~ Regexp in either order; Qundef for the wrong types."""
    state = _enter_status()
    v = rb_str_eq_tilde(_v(a), _v(b), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('=~')
    return ret


def reg_eqq(re, s):
    state = _enter_status()
    v = rb_reg_eqq_fast(_v(re), _v(s), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('===')
    return ret


def last_match0():
    return rffi.cast(lltype.Signed, rb_last_match0())


def last_match1(n):
    return rffi.cast(lltype.Signed, rb_last_match1(_v(n)))


def str_match(s, re):
    state = _enter_status()
    v = rb_str_match_fast(_v(s), _v(re), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('match')
    return ret


def str_tr1(s, frm, to):
    return rffi.cast(lltype.Signed, rb_str_tr1(_v(s), _v(frm), _v(to)))


def str_match_p(s, re):
    """Qundef for the wrong types; a raise inside the search comes back out."""
    state = _enter_status()
    v = rb_str_match_p(_v(s), _v(re), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('match?')
    return ret


def str_match_p_fast(s, re):
    """Unprotected: Qundef unless the shim knows the search cannot raise."""
    return rffi.cast(lltype.Signed, rb_str_match_p_fast(_v(s), _v(re)))


def ss_pos(v):
    return rffi.cast(lltype.Signed, rb_ss_pos(_v(v)))


def ss_set_pos(v, pos):
    return rffi.cast(lltype.Signed, rb_ss_set_pos(_v(v), _v(pos)))


def ss_eos_p(v):
    return rffi.cast(lltype.Signed, rb_ss_eos_p(_v(v)))


def ss_matched_size(v):
    return rffi.cast(lltype.Signed, rb_ss_matched_size(_v(v)))


def ss_skip(v, re):
    """Qundef for the wrong types; a raise inside the match comes back out."""
    state = _enter_status()
    r = rb_ss_skip(_v(v), _v(re), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, r)
    if failed:
        _failed('skip')
    return ret
