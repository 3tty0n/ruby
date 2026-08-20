"""The super path."""
from __future__ import absolute_import

from rpyyarv import dispatch
from rpyyarv import helpers
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import UnsupportedOperation
from rpyyarv.rlib import promote, unroll_safe

from rpyyarv.interp.consts_ids import INITIALIZE, METHOD_MISSING
from rpyyarv.interp.args import NO_KEYWORDS, _kw_to_positional

@unroll_safe
def _super_to_cruby(frame, klass, owner, mid, recv_at, argc, kw_splat,
                    kw_names=NO_KEYWORDS, w_block=None):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    return _super_to_cruby_args(frame, klass, owner, mid, recv_at, args,
                                kw_splat, kw_names, w_block)


@unroll_safe
def _super_to_cruby_args(frame, klass, owner, mid, recv_at, args, kw_splat,
                         kw_names=NO_KEYWORDS, w_block=None):
    """super onto a CRuby-owned method: the one after owner on klass's chain."""
    recv = frame.stack[recv_at]
    if mid == INITIALIZE and len(args) == 0 \
            and owner == value.core_class(value.C_BASIC_OBJECT) \
            and helpers.basic_initialize_pristine():
        _drop(frame, recv_at)
        return value.Q_NIL
    if len(kw_names) > 0:
        args = _kw_to_positional(args, kw_names)
    _drop(frame, recv_at)
    # blk: the frame's own for a bare super, the written one otherwise.
    ret = rubycall.call_super(klass, owner, recv, mid, args,
                              kw_splat or len(kw_names) > 0,
                              _to_proc(w_block))
    if ret == value.Q_UNDEF:
        raise UnsupportedOperation(
            "super from '%s' reaches a method its owner does not define"
            % symbols.name_of(mid))
    _check_block_error()
    return ret


def _ruby2_keywords(frame, recv, recv_at):
    """Module#ruby2_keywords on a registry method: mark its ISeq."""
    mid = _name_mid(frame.stack[recv_at + 1])
    if mid == rubycall.NO_MID:
        return value.Q_UNDEF
    entry = dispatch.lookup_owned(recv, mid)
    if entry is None or entry.kind != dispatch.KIND_ISEQ:
        # A CRuby-owned method: its own Module#ruby2_keywords handles it.
        return value.Q_UNDEF
    w = entry.w_iseq
    # CRuby only marks a *rest method without keyword parameters; else warns.
    if w.rest_start < 0 or len(w.kw_table) > 0 or w.kwrest >= 0:
        return value.Q_UNDEF
    w.r2k = True
    _drop(frame, recv_at)
    return value.Q_NIL


@unroll_safe
def _super_missing_args(frame, mid, recv_at, args, kw_splat, kw_names,
                        w_block):
    """A super with no superclass method reaches method_missing (vm_eval.c)."""
    recv = frame.stack[recv_at]
    if len(kw_names) > 0:
        args = _kw_to_positional(args, kw_names)
    full = [rubycall.sym_value(mid)]
    i = 0
    while i < len(args):
        full.append(args[i])
        i += 1
    _drop(frame, recv_at)
    kw = kw_splat or len(kw_names) > 0
    proc_v = _to_proc(w_block)
    if proc_v != value.Q_NIL:
        return rubycall.call_with_proc(recv, METHOD_MISSING, full, proc_v, kw)
    if kw:
        return rubycall.call_kw(recv, METHOD_MISSING, full)
    return rubycall.call(recv, METHOD_MISSING, full)


@unroll_safe
def invoke_super(frame, w_ci, w_block=None, has_block=False):
    """A send's lookup, resumed above the running method's owner."""
    entry = frame.entry
    if entry is None:
        raise UnsupportedOperation(
            "super outside a method body is not supported (in '%s', %s)"
            % (frame.w_iseq.name, frame.w_iseq.path))
    if w_ci.blockarg:
        # Read before pop, so frame marks it across the alloc (vm_args.c:1119).
        top = frame.sp - 1
        if top < 0:
            raise UnsupportedOperation(
                "super passes a &block the stack does not hold")
        w_block = _block_from_value(frame.block, frame.stack[top])
        frame.pop()
        # super(&nil) suppresses forwarding; only a bare super inherits.
        has_block = True
    blk = w_block if has_block else frame.block
    argc = w_ci.argc
    recv_at = frame.sp - argc - 1
    if recv_at < 0:
        raise UnsupportedOperation(
            "super with %d argument(s) underflows the stack" % argc)
    if not w_ci.simple and len(w_ci.kw_names) == 0 and not w_ci.kw_splat \
            and not w_ci.splat:
        raise UnsupportedOperation(
            "super in '%s' passes arguments RPyYARV does not support"
            % symbols.name_of(entry.mid))
    if w_ci.kw_splat:
        _kw_splat_hash(frame, recv_at + argc)

    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    klass = promote(value.class_of(recv))
    # CRuby is asked: the chain above owner may hold iclasses we lack.
    owner = dispatch.super_owner(klass, entry.owner, entry.mid)
    target = None
    if owner != value.Q_NIL:
        target = dispatch.lookup_owned(owner, entry.mid)
    if target is None and owner == value.Q_NIL:
        # vm_call_method_missing: a missing super falls back to it.
        kw_splat = w_ci.kw_splat
        if w_ci.splat:
            trailing = 1 if kw_splat else len(w_ci.kw_names)
            args = _splat_args(frame, recv_at + 1, argc - trailing, trailing)
            kw_splat = _splat_kw(args, kw_splat, trailing)
        else:
            args = []
            i = 0
            while i < argc:
                args.append(frame.stack[recv_at + 1 + i])
                i += 1
        return _super_missing_args(frame, entry.mid, recv_at, args,
                                   kw_splat, w_ci.kw_names, blk)
    if w_ci.splat:
        trailing = 1 if w_ci.kw_splat else len(w_ci.kw_names)
        args = _splat_args(frame, recv_at + 1, argc - trailing, trailing)
        kw_splat = _splat_kw(args, w_ci.kw_splat, trailing)
        if target is None:
            return _super_to_cruby_args(frame, klass, entry.owner, entry.mid,
                                        recv_at, args, kw_splat,
                                        w_ci.kw_names, blk)
        if target.kind != dispatch.KIND_ISEQ:
            return _attr_send_args(frame, target, recv, recv_at, args, blk)
        return _enter_args(frame, target, recv, recv_at, args, entry.mid,
                           blk, w_ci.kw_names, kw_splat)
    if target is None:
        return _super_to_cruby(frame, klass, entry.owner, entry.mid, recv_at,
                               argc, w_ci.kw_splat, w_ci.kw_names, blk)
    if target.kind != dispatch.KIND_ISEQ:
        return _attr_send(frame, target, recv, recv_at, argc, blk)
    return _enter(frame, target, recv, recv_at, argc,
                  entry.mid, blk, w_ci.kw_names, w_ci.kw_splat)


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.sends import _attr_send, _attr_send_args, _enter, _enter_args, _kw_splat_hash, _name_mid, _splat_args, _splat_kw
from rpyyarv.interp.blocks import _block_from_value, _to_proc
from rpyyarv.interp.callbacks import _check_block_error
from rpyyarv.interp.stackops import _drop
