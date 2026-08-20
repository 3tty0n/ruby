"""String, StringScanner and Kernel#format fast paths."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import value
from rpyyarv.rlib import promote
from rpyyarv.helpers.core import *
from rpyyarv.helpers.core import (_core_op, _cruby_owns, _owned_by_core,
                                  _str_eq_op)


def str_to_s(recv):
    """String#to_s is the receiver; not for a subclass (string.c:11845)."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _core_op(value.C_STRING, B_STR_TO_S, TO_S):
        return value.Q_UNDEF
    return recv


def str_start_with(recv, prefix):
    """String#start_with? with one String arg: a byte compare in the shim."""
    if not value.is_plain_string(recv) \
            or not _core_op(value.C_STRING, B_STR_START_WITH, START_WITH_P):
        return value.Q_UNDEF
    return boot.str_start_with(recv, prefix)


def str_casecmp(recv, arg):
    """String#casecmp for two Strings: C only, nothing to raise."""
    if value.is_immediate(recv) or value.is_immediate(arg) \
            or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, CASECMP):
        return value.Q_UNDEF
    return boot.str_casecmp(recv, arg)


def str_case(recv, mid):
    """String#down/upcase(!): shim takes 7-bit only; a subclass goes back."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, mid):
        return value.Q_UNDEF
    if mid == DOWNCASE:
        return boot.str_downcase(recv)
    if mid == DOWNCASE_BANG:
        return boot.str_downcase_bang(recv)
    if mid == UPCASE:
        return boot.str_upcase(recv)
    return boot.str_upcase_bang(recv)


def str_dup(recv):
    """String#dup on the exact class; string.c defines its own dup since 3.3."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, DUP):
        return value.Q_UNDEF
    return boot.str_dup(recv)


def ss_zero(recv, mid):
    """StringScanner's struct reads; the shim's TypedData check is the guard."""
    if value.is_immediate(recv):
        return value.Q_UNDEF
    if mid == POS_MID:
        return boot.ss_pos(recv)
    if mid == EOS_P_MID:
        return boot.ss_eos_p(recv)
    return boot.ss_matched_size(recv)


def ss_set_pos(recv, arg):
    if value.is_immediate(recv):
        return value.Q_UNDEF
    return boot.ss_set_pos(recv, arg)


def ss_skip(recv, arg):
    if value.is_immediate(recv) or value.is_immediate(arg):
        return value.Q_UNDEF
    return boot.ss_skip(recv, arg)


def str_byteslice(recv, beg, length):
    if value.is_immediate(recv) or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, BYTESLICE):
        return value.Q_UNDEF
    return boot.str_byteslice2(recv, beg, length)


def kernel_format(recv, fmt, args, mid):
    """Kernel#format/sprintf via rb_str_format; the shim rb_protects it."""
    if modules.kernel == 0 or not value.is_plain_string(fmt):
        return value.Q_UNDEF
    klass = promote(value.class_of(recv))
    if dispatch.lookup(klass, mid) is not None:
        return value.Q_UNDEF
    if dispatch.owner_of(klass, mid) != modules.kernel:
        return value.Q_UNDEF
    return boot.str_format(fmt, args)


def cgi_escape_html(str_arg):
    """CGI.escapeHTML; the shim answers Qundef for anything not ascii."""
    if value.is_immediate(str_arg):
        return value.Q_UNDEF
    return boot.cgi_escape_html(str_arg)


def str_uminus(recv):
    """String#-@: the interned frozen copy."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, UMINUS):
        return value.Q_UNDEF
    return boot.str_uminus(recv)


def str_tr(recv, frm, to):
    """String#tr of one plain byte for another; anything wider goes back."""
    if not value.is_plain_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, TR):
        return value.Q_UNDEF
    return boot.str_tr1(recv, frm, to)


def str_index(recv, arg):
    """String#index of a String needle, both 7-bit, no offset."""
    if value.is_immediate(recv) or value.is_immediate(arg) \
            or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, INDEX_MID):
        return value.Q_UNDEF
    return boot.str_index_of(recv, arg)


def str_length(recv, mid):
    """String#length/#size: character count, byte count for a 7-bit string."""
    if value.is_immediate(recv) or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, mid):
        return value.Q_UNDEF
    return boot.str_length(recv)


def str_bytesize(recv):
    """String#bytesize is RSTRING_LEN: no allocation, nothing to raise."""
    if value.is_immediate(recv) or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, BYTESIZE):
        return value.Q_UNDEF
    return value.int2fix(boot.str_bytesize(recv))


def str_ascii_only_p(recv):
    """String#ascii_only?: the coderange scan neither allocates nor raises."""
    if value.is_immediate(recv) or not boot.is_string(recv):
        return value.Q_UNDEF
    if not _owned_by_core(recv, value.C_STRING, ASCII_ONLY_P):
        return value.Q_UNDEF
    return boot.str_ascii_only_p(recv)


def _str_eq(a, b):
    """vm_opt_str_eq (vm_insnhelper.c:2540); no to_str false (string.c:4271)."""
    if not (value.is_plain_string(a) and _str_eq_op()):
        return value.Q_UNDEF
    v = boot.str_eq(a, b)
    if v != value.Q_UNDEF:
        return v
    # TODO: a respond_to_missing? claiming an undefined to_str reads as none.
    if value.is_immediate(b) \
            and dispatch.owner_of(promote(value.class_of(b)),
                                  TO_STR) == value.Q_NIL:
        return value.Q_FALSE
    return value.Q_UNDEF


def str_concat(a, b):
    """String#<< a String or byte; frozen or re-encoding stays with CRuby."""
    if not value.is_plain_string(a):
        return value.Q_UNDEF
    if not (value.is_plain_string(b) or value.is_fixnum(b)):
        return value.Q_UNDEF
    if not _core_op(value.C_STRING, B_STR_LTLT, LTLT):
        return value.Q_UNDEF
    v = boot.str_append(a, b)
    if v != value.Q_UNDEF or not value.is_plain_string(b):
        return v
    # The raw arm refused: still one protected call, not a full send.
    return boot.str_push(a, b)


def str_freeze_pristine():
    """String#freeze still CRuby's, so opt_str_freeze may push the literal."""
    return (_cruby_owns(B_STR_FREEZE)
            and dispatch.lookup_core(value.core_class(value.C_STRING),
                                     FREEZE) is None)
