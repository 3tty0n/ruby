"""Stack shuffling helpers for the interpreter loop."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import dispatch
from rpyyarv import helpers
from rpyyarv import optable
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.error import UnsupportedOperation
from rpyyarv.rlib import dont_look_inside, unroll_safe

from rpyyarv.interp.consts_ids import BUFFER, TO_S

@unroll_safe
def _local_frame(frame, packed):
    if packed == (packed & optable.LOCAL_SLOT_MASK):
        return frame
    return _outer_frame(frame, packed >> optable.LOCAL_LEVEL_SHIFT)


@unroll_safe
def _drop(frame, sp):
    while frame.sp > sp:
        frame.pop()


@unroll_safe
def _pushtoarray(frame, n):
    """rb_ary_cat of the n topmost onto the Array under them, left on stack."""
    at = frame.sp - n
    if at < 1:
        raise UnsupportedOperation('pushtoarray %d underflows the stack' % n)
    # Restated so the codewriter sees every stack index as non-negative.
    below = at - 1
    assert below >= 0
    ary = frame.slots[below]
    base = _ary_len(ary)
    i = 0
    while i < n:
        j = at + i
        assert j >= 0
        rubycall.ary_store(ary, base + i, frame.slots[j])
        i += 1
    _drop(frame, at)


@dont_look_inside
def _to_s(v):
    if rubycall.is_string(v):
        return v
    return rubycall.call0(v, TO_S)


@dont_look_inside
def _concat(parts):
    return boot.str_concat(parts)


@unroll_safe
def _newarray(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('newarray %d underflows the stack' % n)
    # Copied but not popped: the frame marks them until the shim has them.
    values = [0] * n
    i = 0
    while i < n:
        values[i] = frame.slots[at + i]
        i += 1
    v = rubycall.ary_new(values)
    _drop(frame, at)
    return v


# vm_opt_newarray_send_type (vm_core.h), indexed by method-1.
NEWARRAY_SEND_MID = [helpers.MAX, helpers.MIN, helpers.HASH, helpers.PACK,
                     helpers.PACK, helpers.INCLUDE_P]


@unroll_safe
def _newarray_send(frame, n, meth):
    """vm_opt_newarray_send's fallback: build the array, send the method."""
    argc = optable.NEWARRAY_SEND_ARGC[meth - 1]
    if argc == 2:
        buffer = frame.pop()
        arg = frame.pop()
        count = n - 2
        at = frame.sp - count
        if at < 0 or count < 0:
            raise UnsupportedOperation(
                'opt_newarray_send %d underflows the stack' % n)
        values = [0] * count
        i = 0
        while i < count:
            values[i] = frame.slots[at + i]
            i += 1
        v_ary = rubycall.ary_new(values)
        _drop(frame, at)
        # Before the keyword Hash exists: the fused instruction allocates none.
        if send_owners.array_pack != 0 \
                and dispatch.owner_of(value.class_of(v_ary), helpers.PACK) \
                == send_owners.array_pack:
            v = boot.pack_double_into(v_ary, arg, buffer)
            if v != value.Q_UNDEF:
                debug.count_native()
                return v
        kwargs = boot.hash_new(1)
        boot.hash_aset(kwargs, rubycall.sym_value(BUFFER), buffer)
        return rubycall.call_kw(v_ary, helpers.PACK, [arg, kwargs])
    at = frame.sp - n
    m = n - argc
    if at < 0 or m < 0:
        raise UnsupportedOperation('opt_newarray_send %d underflows the stack'
                                   % n)
    values = [0] * m
    i = 0
    while i < m:
        values[i] = frame.slots[at + i]
        i += 1
    arg = 0
    if argc == 1:
        top = frame.sp - 1
        assert top >= 0
        arg = frame.slots[top]
    v_ary = rubycall.ary_new(values)
    _drop(frame, at)
    frame.push(v_ary)
    if argc == 1:
        frame.push(arg)
    return _opt_send(frame, NEWARRAY_SEND_MID[meth - 1], argc)


@unroll_safe
def _newhash(frame, n):
    """n/2 pairs, left in the marked frame until rb_hash_aset copied them."""
    at = frame.sp - n
    if at < 0 or n % 2 != 0:
        raise UnsupportedOperation('newhash %d underflows the stack' % n)
    h = rubycall.hash_new(n // 2)
    i = 0
    while i < n:
        rubycall.hash_aset(h, frame.slots[at + i], frame.slots[at + i + 1])
        i += 2
    _drop(frame, at)
    return h


@unroll_safe
def _dupn(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('dupn %d underflows the stack' % n)
    i = 0
    while i < n:
        frame.push(frame.slots[at + i])
        i += 1


@unroll_safe
def _adjuststack(frame, n):
    if frame.sp - n < 0:
        raise UnsupportedOperation('adjuststack %d underflows the stack' % n)
    i = 0
    while i < n:
        frame.pop()
        i += 1


@unroll_safe
def _reverse(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('opt_reverse %d underflows the stack' % n)
    i = 0
    while i < n // 2:
        lo = at + i
        hi = frame.sp - 1 - i
        assert lo >= 0
        assert hi >= 0
        v = frame.slots[lo]
        frame.slots[lo] = frame.slots[hi]
        frame.slots[hi] = v
        i += 1


@unroll_safe
def _expand(frame, v, n, flag=0):
    """vm_expandarray: flag 1 pushes the rest, flag 2 fills from the end."""
    if not value.is_array(v):
        v = boot.ary_to_ary(v)
    size = value.ary_len(v)
    if flag & 2:
        i = 0
        while i < n - size:
            frame.push(value.Q_NIL)
            i += 1
        j = 0
        while i < n:
            frame.push(value.ary_at(v, size - j - 1))
            i += 1
            j += 1
        if flag & 1:
            head = size - j
            assert head >= 0
            frame.push(boot.ary_subseq(v, 0, head))
        return
    if flag & 1:
        if n > size:
            frame.push(boot.ary_subseq(v, size, 0))
        else:
            frame.push(boot.ary_subseq(v, n, size - n))
    i = n - 1
    while i >= 0:
        if i < size:
            frame.push(value.ary_at(v, i))
        else:
            frame.push(value.Q_NIL)
        i -= 1


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.sends import _ary_len, _opt_send, send_owners
from rpyyarv.interp.blocks import _outer_frame
