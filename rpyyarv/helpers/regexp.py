"""Regexp and String-match fast paths."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.helpers.core import *
from rpyyarv.helpers.core import _owned_by_core


def str_match_p(recv, arg):
    """String#match? of a Regexp: the shim answers Qundef when it may raise."""
    if value.is_immediate(recv) or value.is_immediate(arg) \
            or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, MATCH_P):
        return value.Q_UNDEF
    v = boot.str_match_p_fast(recv, arg)
    if v != value.Q_UNDEF:
        return v
    return boot.str_match_p(recv, arg)


def str_gsub2(recv, pat, rep, mid):
    """gsub/sub(!): the shim rules out backref escapes and encoding mismatch."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, mid):
        return value.Q_UNDEF
    return boot.str_gsub2(recv, pat, rep, rubycall.rid(mid), mid)


def str_eq_tilde(a, b):
    """String#=~ / Regexp#=~: rb_reg_match is all of it, backref included."""
    if value.is_plain_string(a):
        if not _owned_by_core(a, value.C_STRING, MATCH_TILDE):
            return value.Q_UNDEF
        return boot.str_eq_tilde(a, b)
    if value.is_plain_string(b):
        return boot.str_eq_tilde(a, b)
    return value.Q_UNDEF


def reg_eqq(re, s):
    """Regexp#=== via rb_reg_match; subclass or non-String falls back."""
    if value.is_immediate(re) or not value.is_plain_string(s):
        return value.Q_UNDEF
    return boot.reg_eqq(re, s)


def last_match0():
    return boot.last_match0()


def last_match1(n):
    """Regexp.last_match(n); anything but a Fixnum n falls back."""
    if not value.is_fixnum(n):
        return value.Q_UNDEF
    return boot.last_match1(n)


def str_match(recv, arg):
    """String#match Regexp, no offset, no block: rb_reg_match plus backref."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, MATCH_MID):
        return value.Q_UNDEF
    return boot.str_match(recv, arg)
