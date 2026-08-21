"""Ivar fast path: shape-indexed field reads/writes off the raw object."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import value
from rpyyarv import rubycall
from rpyyarv.rlib import (elidable, dont_look_inside, intmask, promote,
                          r_uint, raw_word, set_raw_word)
from rpyyarv.dispatch.core import Version
from rpyyarv.dispatch.caches import iv_slot, method_state_changed
from rpyyarv.dispatch.consts import invalidate_consts


def _data_fields(obj, flags):
    """A typed T_DATA's fields; 0 for a shareable one (variable.c:1220)."""
    if (flags & value.T_MASK) == value.T_DATA \
            and (flags & (value.FL_TYPED_DATA | value.FL_SHAREABLE)) \
            == value.FL_TYPED_DATA:
        return raw_word(obj, value.FIELDS_WORD)
    return 0


def _class_fields(obj, hdr):
    """A class's fields object; 0 for a boxable one (internal/class.h:314)."""
    if hdr & value.RCLASS_BOXABLE:
        return 0
    return raw_word(obj, value.CLASS_FIELDS_WORD)


def ivar_get(obj, mid):
    """T_OBJECT reads compile to a shape guard plus a raw field load."""
    if obj != 0 and (obj & value.IMMEDIATE_MASK) == 0:
        flags = raw_word(obj, value.FLAGS_WORD)
        fields = obj
        # One promoted word, so the four tests below fold into its one guard.
        hdr = promote(flags & value.IV_HEADER_MASK)
        kind = hdr & value.T_MASK
        klass = kind == value.T_CLASS or kind == value.T_MODULE
        if kind != value.T_OBJECT:
            if klass:
                # Re-read: growing ivars replaces the fields object.
                fields = _class_fields(obj, hdr)
            else:
                fields = _data_fields(obj, flags)
            if fields != 0:
                hdr = promote(raw_word(fields, value.FLAGS_WORD)
                              & value.IV_HEADER_MASK)
        if fields != 0:
            shape_id = (hdr >> value.SHAPE_SHIFT) & value.SHAPE_MASK
            slot = iv_slot(shape_id, rubycall.const_rid(mid))
            if slot >= 0:
                if hdr & value.ROBJECT_HEAP:
                    got = raw_word(raw_word(fields, value.FIELDS_WORD), slot)
                else:
                    got = raw_word(fields, value.FIELDS_WORD + slot)
                # Unshareable read off the main ractor raises (variable.c:1457).
                if not klass or value.is_immediate(got) \
                        or (raw_word(got, value.FLAGS_WORD)
                            & value.FL_SHAREABLE):
                    return got
            if slot == -1:
                return value.Q_NIL
    return _ivar_get_slow(obj, mid)


@dont_look_inside
def _ivar_get_slow(obj, mid):
    return boot.ivar_get(obj, rubycall.rid(mid))


class _Barrier(object):
    # Quasi-immutable: install() writes it once, before any Ruby code runs.
    _immutable_fields_ = ['direct?']

    def __init__(self):
        self.direct = False


barrier = _Barrier()


class TransEntry(object):
    _immutable_fields_ = ['after', 'slot']

    def __init__(self, after, slot):
        self.after = after
        self.slot = slot


class _Trans(object):
    # Quasi-immutable: recording an edge drops traces that folded its absence.
    _immutable_fields_ = ['version?']

    def __init__(self):
        self.tab = {}       # (shape_id, CRuby ID) -> TransEntry
        self.version = Version()


trans = _Trans()


@elidable
def _iv_transition(shape_id, rid, version):
    return trans.tab.get((shape_id, rid), None)


def ivar_set(obj, mid, v):
    """Raw store; an immediate needs no barrier (ruby/internal/gc.h:788)."""
    if obj != 0 and (obj & value.IMMEDIATE_MASK) == 0:
        immediate = value.is_immediate(v)
        if immediate or barrier.direct:
            flags = raw_word(obj, value.FLAGS_WORD)
            # One promoted word: the four tests below fold into its guard.
            hdr = promote(flags & value.IV_SET_HEADER_MASK)
            if (hdr & value.FL_FREEZE) == 0:
                # Only an object holding its own fields may gain one here.
                own = (hdr & value.T_MASK) == value.T_OBJECT
                fields = obj
                if not own:
                    fields = _data_fields(obj, flags)
                    if fields != 0:
                        flags = raw_word(fields, value.FLAGS_WORD)
                        hdr = promote(flags & value.IV_SET_HEADER_MASK)
                if fields != 0:
                    shape_id = (hdr >> value.SHAPE_SHIFT) & value.SHAPE_MASK
                    rid = rubycall.const_rid(mid)
                    slot = iv_slot(shape_id, rid)
                    after = shape_id
                    if slot == -1 and own:
                        entry = _iv_transition(shape_id, rid, trans.version)
                        if entry is not None:
                            after = entry.after
                            slot = entry.slot
                    if slot >= 0:
                        if hdr & value.ROBJECT_HEAP:
                            set_raw_word(raw_word(fields, value.FIELDS_WORD),
                                         slot, v)
                        else:
                            set_raw_word(fields, value.FIELDS_WORD + slot, v)
                        if after != shape_id:
                            # Field first: a new shape exposes an empty slot.
                            set_raw_word(obj, value.FLAGS_WORD,
                                         intmask((r_uint(flags)
                                                  & r_uint(value.SHAPE_FLAG_MASK))
                                                 | (r_uint(after)
                                                    << value.SHAPE_SHIFT)))
                        if not immediate:
                            boot.obj_written(fields, v)
                        return
                    if slot == -1 and own:
                        _ivar_add_slow(obj, shape_id, rid, v)
                        return
    _ivar_set_slow(obj, mid, v)


@dont_look_inside
def _ivar_add_slow(obj, before, rid, v):
    """First store allocates the edge in CRuby; the edge is permanent."""
    boot.ivar_set(obj, rid, v)
    if (before, rid) in trans.tab:
        return
    after = (raw_word(obj, value.FLAGS_WORD)
             >> value.SHAPE_SHIFT) & value.SHAPE_MASK
    slot = boot.shape_add_ivar_slot(before, after, rid)
    if slot < 0:
        return
    trans.tab[(before, rid)] = TransEntry(after, slot)
    trans.version = Version()


@dont_look_inside
def _ivar_set_slow(obj, mid, v):
    boot.ivar_set(obj, rubycall.rid(mid), v)


def check_object_layout():
    """The ivar fast path reads RObject by hand; refuse a bad CRuby."""
    got = boot.object_layout()
    want = [value.SHAPE_SHIFT, value.SHAPE_ID_BITS, value.ROBJECT_HEAP,
            value.FIELDS_WORD, value.T_MASK, value.T_OBJECT,
            value.FL_FREEZE, value.SHAPE_ID_IN_FLAGS, value.T_DATA,
            value.FL_TYPED_DATA, value.FIELDS_WORD, value.FL_SHAREABLE,
            value.CLASS_FIELDS_WORD, value.RCLASS_BOXABLE]
    return got == want


def install():
    value.install_classes(boot.core_classes())
    barrier.direct = boot.wb_direct()
    boot.set_const_hook(invalidate_consts)
    boot.set_method_hook(method_state_changed)
