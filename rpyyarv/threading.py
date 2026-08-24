"""Safe entry to serialized RPython state from CRuby Ractor threads."""

from rpython.rlib import rgil

from rpyyarv.rlib import dont_look_inside, unchecked_stack_start


@dont_look_inside
def enter_callback():
    """Take RPython GIL only when C called us on a foreign thread."""
    if rgil.am_I_holding_the_GIL():
        return False
    rgil.acquire_maybe_in_new_thread()
    return True


@dont_look_inside
def leave_callback(acquired):
    if acquired:
        rgil.release()


@dont_look_inside
def _enter():
    rgil.acquire_maybe_in_new_thread()
    unchecked_stack_start()
    from rpyyarv import boot
    from rpyyarv import interp
    if boot.foreign_depth() == 0:
        boot.enter_foreign_depth()
    interp.disable_jit_for_ractor()


@dont_look_inside
def _leave():
    from rpyyarv import interp
    interp.configure_jitparams()
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
