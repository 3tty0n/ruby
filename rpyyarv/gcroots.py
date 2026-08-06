"""Layer (b) of the VALUE-direct GC design: the VALUEs that escaped into the
RPython heap.

CRuby's conservative stack scan already covers VALUEs living in machine
registers and C/JIT stack frames. What it cannot see are the frame stacks,
the frame locals and the per-ISeq constant pools, all of which are RPython
objects. This module keeps them enumerable and hands them to CRuby through
the shim's mark hook.
"""

import boot
import value
from rlib import dont_look_inside
from rpython.rtyper.annlowlevel import llhelper


class Registry(object):
    def __init__(self):
        self.top = None         # innermost live Frame
        self.consts = []        # every loaded ISeq's constant pool
        self.pinned = []        # VALUEs built during load, before their pool
        self.classes = []       # classes RPyYARV defined, keys of the registry


state = Registry()


def register_class(v):
    if not value.is_immediate(v):
        state.classes.append(v)


def register_consts(consts):
    if len(consts) > 0:
        state.consts.append(consts)


def keepalive(v):
    if not value.is_immediate(v):
        state.pinned.append(v)


def release_load_temporaries():
    state.pinned = []


def push_frame(frame):
    frame.prev_frame = state.top
    state.top = frame


def pop_frame(frame):
    state.top = frame.prev_frame
    frame.prev_frame = None


def _mark_array(a):
    i = 0
    n = len(a)
    while i < n:
        v = a[i]
        if not value.is_immediate(v):
            boot.gc_mark_value(v)
        i += 1


@dont_look_inside
def mark_roots():
    # Kept apart from _mark_array: this one is resized, the pools are not,
    # and the annotator will not merge the two list kinds.
    pinned = state.pinned
    k = 0
    while k < len(pinned):
        v = pinned[k]
        if not value.is_immediate(v):
            boot.gc_mark_value(v)
        k += 1
    klasses = state.classes
    k = 0
    while k < len(klasses):
        boot.gc_mark_value(klasses[k])
        k += 1
    pools = state.consts
    i = 0
    while i < len(pools):
        _mark_array(pools[i])
        i += 1
    # Reading a virtualizable's fields from here forces it; the design doc
    # accepts that for now and jit-summary's "virtualizables forced" measures
    # what it costs.
    f = state.top
    while f is not None:
        _mark_array(f.stack)
        _mark_array(f.locals)
        if not value.is_immediate(f.self_val):
            boot.gc_mark_value(f.self_val)
        if not value.is_immediate(f.cref):
            boot.gc_mark_value(f.cref)
        f = f.prev_frame


def install():
    boot.set_mark_hook(llhelper(boot.MARK_HOOK, mark_roots))
