"""vm.c + eval.c + cont.c: boot, run, fibers, and VM hooks."""
from __future__ import absolute_import
import os

from rpython.rtyper.lltypesystem import lltype, rffi

from rpyyarv.boot._core import (_ext, _v, VALUE, VOIDP, INTP, _ARCH,
                                CONST_HOOK, METHOD_HOOK, FIBER_SAVE_HOOK,
                                FIBER_ARRIVE_HOOK, FIBER_BORN_HOOK,
                                FIBER_KEY_HOOK, THREAD_HOOK)


rb_set_thread_callbacks = _ext('rpyyarv_set_thread_callbacks',
                               [THREAD_HOOK, THREAD_HOOK,
                                THREAD_HOOK, THREAD_HOOK], lltype.Void)


rb_activate_threads = _ext('rpyyarv_activate_threads', [], lltype.Void,
                           reenters=True)


rb_ractor_class_p = _ext('rpyyarv_ractor_class_p', [VALUE], rffi.INT)


rb_ractor_p = _ext('rpyyarv_ractor_p', [VALUE], rffi.INT)


rb_ractor_callback_p = _ext('rpyyarv_ractor_callback_p', [], rffi.INT)


rb_native_ractors_p = _ext('rpyyarv_native_ractors_p', [], rffi.INT)


rb_native_ractors_poll = _ext('rpyyarv_native_ractors_poll', [VALUE],
                              lltype.Void, reenters=True)


rb_boot = _ext('rpyyarv_boot', [rffi.INT, rffi.CCHARPP, INTP], VOIDP)


rb_cleanup = _ext('rpyyarv_cleanup', [rffi.INT], rffi.INT)


rb_run_node = _ext('rpyyarv_run_node', [VOIDP], rffi.INT, reenters=True)


rb_iseqw_new = _ext('rpyyarv_iseqw_new', [VOIDP], VALUE)


rb_iseqw_ptr = _ext('rpyyarv_iseqw_ptr', [VALUE], VOIDP)


rb_iseqw_children = _ext('rpyyarv_iseqw_children', [VALUE], VALUE,
                         reenters=True)


rb_iseqw_child_index = _ext('rpyyarv_iseqw_child_index',
                            [VALUE, VALUE, rffi.LONG], rffi.LONG,
                            reenters=True)


rb_cref_new = _ext('rb_rpyyarv_cref_new', [VOIDP, VALUE, rffi.INT], VOIDP)


class _NativeCrefState(object):
    def __init__(self):
        self.top = 0


native_cref_state = _NativeCrefState()


rb_top_self = _ext('rpyyarv_top_self', [], VALUE)


rb_set_const_hook = _ext('rpyyarv_set_const_hook', [CONST_HOOK], lltype.Void)


rb_fiber_killed_value = _ext('rpyyarv_fiber_killed_value', [], VALUE)


rb_rethrow_if_fiber_kill = _ext('rpyyarv_rethrow_if_fiber_kill', [VALUE],
                                rffi.INT)


rb_set_fiber_hooks = _ext('rpyyarv_set_fiber_hooks',
                          [FIBER_SAVE_HOOK, FIBER_ARRIVE_HOOK, FIBER_BORN_HOOK,
                           FIBER_KEY_HOOK, VOIDP, VOIDP], lltype.Void)


rb_set_method_hook = _ext('rpyyarv_set_method_hook', [METHOD_HOOK], lltype.Void)


rb_vm_core = _ext('rpyyarv_vm_core', [], VALUE, reenters=True)


rb_set_block_unwind = _ext('rpyyarv_set_block_unwind', [], lltype.Void)


rb_bop_mask = _ext('rpyyarv_bop_mask', [INTP], VALUE, reenters=True)


rb_current_receiver = _ext('rpyyarv_current_receiver', [], VALUE,
                           reenters=True)


def top_self():
    return rffi.cast(lltype.Signed, rb_top_self())


def iseqw_ptr(iseqw):
    return rffi.cast(lltype.Signed, rb_iseqw_ptr(_v(iseqw)))


def iseqw_children(iseqw):
    return rffi.cast(lltype.Signed, rb_iseqw_children(_v(iseqw)))


def iseqw_child_index(children, ary, hint):
    return rffi.cast(lltype.Signed,
                     rb_iseqw_child_index(_v(children), _v(ary),
                                          rffi.cast(rffi.LONG, hint)))


def native_cref(cref):
    if cref is None:
        if native_cref_state.top == 0:
            native_cref_state.top = rffi.cast(
                lltype.Signed,
                rb_cref_new(lltype.nullptr(rffi.VOIDP.TO), _v(0),
                            rffi.cast(rffi.INT, 0)))
        return native_cref_state.top
    if cref.native != 0:
        return cref.native
    outer = native_cref(cref.outer)
    cref.native = rffi.cast(lltype.Signed, rb_cref_new(
        rffi.cast(rffi.VOIDP, outer), _v(cref.klass),
        rffi.cast(rffi.INT, 1 if cref.by_eval else 0)))
    return cref.native


def current_receiver():
    return rffi.cast(lltype.Signed, rb_current_receiver())


def vm_core():
    return rffi.cast(lltype.Signed, rb_vm_core())


def set_block_unwind():
    """Tell the shim the block it is running left early; see boot_shim.h."""
    rb_set_block_unwind()


def set_thread_callbacks(enter, leave, acquire, release):
    rb_set_thread_callbacks(enter, leave, acquire, release)


def activate_threads():
    rb_activate_threads()


def ractor_class_p(v):
    return rffi.cast(lltype.Signed, rb_ractor_class_p(_v(v))) != 0


def ractor_p(v):
    return rffi.cast(lltype.Signed, rb_ractor_p(_v(v))) != 0


def ractor_callback_p():
    return rffi.cast(lltype.Signed, rb_ractor_callback_p()) != 0


def native_ractors_p():
    return rffi.cast(lltype.Signed, rb_native_ractors_p()) != 0


def native_ractors_poll(waited):
    rb_native_ractors_poll(_v(waited))


def bop_mask():
    """(pair count, one bit per redefined pair) as the shim orders them."""
    with lltype.scoped_alloc(INTP.TO, 1) as count:
        count[0] = rffi.cast(rffi.INT, 0)
        v = rffi.cast(lltype.Signed, rb_bop_mask(count))
        return rffi.cast(lltype.Signed, count[0]), v


def fiber_killed_value():
    return rffi.cast(lltype.Signed, rb_fiber_killed_value())


def rethrow_if_fiber_kill(v):
    """Fiber#kill resumes its fatal unwind here, not as a raise into CRuby."""
    rb_rethrow_if_fiber_kill(_v(v))


def set_fiber_hooks(park, unpark, born, died, base_slot, top_slot):
    rb_set_fiber_hooks(park, unpark, born, died, base_slot, top_slot)


def set_const_hook(fn):
    rb_set_const_hook(fn)


def set_method_hook(fn):
    rb_set_method_hook(fn)


class _Node(object):
    # The compiled main script, kept so run_node() can hand it back to CRuby.
    def __init__(self):
        self.ptr = lltype.nullptr(VOIDP.TO)


node = _Node()


def _uninstalled_dirs():
    """The uninstalled build's lib/ and .ext, missed by the exe path."""
    build = os.environ.get('RPYYARV_BUILD')
    if build is None or build == '':
        return []
    cut = build.rfind('/')
    if cut <= 0:
        return []
    ext = build + '/.ext'
    # rbconfig.rb is generated into the build root, not into .ext/common.
    return [build[:cut] + '/lib', ext + '/common', build, ext + '/' + _ARCH]


def _boot_argv(argv):
    """-I, not RUBYLIB: allocating before ruby_init swings AWFY towers 38%."""
    args = [argv[0]]
    if os.environ.get('RPYYARV_GEMS') != '1':
        args.append('--disable-gems')
    for d in _uninstalled_dirs():
        args.append('-I' + d)
    return args + argv[1:]


def boot(argv):
    """Return (iseqw, status). iseqw is 0 when there is no ISeq to run."""
    argv = _boot_argv(argv)
    # Never freed: ruby_sysinit keeps it in origarg (ruby.c) for process life.
    c_argv = rffi.liststr2charpp(argv)
    with lltype.scoped_alloc(INTP.TO, 1) as status:
        status[0] = rffi.cast(rffi.INT, 0)
        n = rb_boot(rffi.cast(rffi.INT, len(argv)), c_argv, status)
        if not n:
            return 0, rffi.cast(lltype.Signed, status[0])
        node.ptr = n
        return rffi.cast(lltype.Signed, rb_iseqw_new(n)), 0


def run_node():
    """Runs the script and cleans up; the answer is the process exit status."""
    return rffi.cast(lltype.Signed, rb_run_node(node.ptr))


def cleanup(status):
    return rffi.cast(lltype.Signed, rb_cleanup(rffi.cast(rffi.INT, status)))
