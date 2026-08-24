"""Safe entry to serialized RPython state from CRuby Ractor threads."""

import os

from rpython.rlib import rgil

from rpyyarv.rlib import dont_look_inside, unchecked_stack_start


# A translation-time switch: ordinary binaries retain the single-thread GC.
ENABLED = os.environ.get('RPYYARV_RACTOR_BUILD') == '1'


@dont_look_inside
def enter_callback():
    """Take RPython GIL only when C called us on a foreign thread."""
    if not ENABLED:
        return 0
    acquired = not rgil.am_I_holding_the_GIL()
    if acquired:
        rgil.acquire_maybe_in_new_thread()
    from rpyyarv import boot
    if not boot.ractor_callback_p():
        return 1 if acquired else 0
    from rpyyarv import interp
    interp.disable_jit_for_ractor()
    return (1 if acquired else 0) | 2


@dont_look_inside
def leave_callback(state):
    if not ENABLED:
        return
    if state & 2:
        from rpyyarv import interp
        interp.configure_jitparams()
    if state & 1:
        rgil.release()


@dont_look_inside
def _enter():
    rgil.acquire_maybe_in_new_thread()
    unchecked_stack_start()
    from rpyyarv import boot
    if boot.foreign_depth() == 0:
        boot.enter_foreign_depth()


@dont_look_inside
def _leave():
    rgil.release()


@dont_look_inside
def _acquire_gil():
    rgil.acquire()


@dont_look_inside
def _release_gil():
    rgil.release()


def install():
    from rpyyarv import boot
    boot.set_thread_callbacks(_enter, _leave, _acquire_gil, _release_gil)
