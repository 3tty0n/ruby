"""The CRuby to RPython entry points."""
from __future__ import absolute_import

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import dispatch
from rpyyarv import gcroots
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import threading
from rpyyarv import value
from rpyyarv.error import RPyYarvError, RubyException, UnsupportedOperation
from rpyyarv.frame import Frame
from rpyyarv.rlib import (StackOverflow, check_stack_overflow,
                          dont_look_inside, unchecked_stack_start,
                          unchecked_stack_stop)

from rpyyarv.interp.args import NO_KEYWORDS, _arity_error, _refuse_iseq, setup_params

def _sub_self(handle, cruby_self):
    """Q_UNDEF keeps the block's own self; else the self CRuby yielded under."""
    v = boot.as_signed(cruby_self)
    if v == blocks.selves[handle]:
        return value.Q_UNDEF
    return v


def block_callback(handle, argc, argv, cruby_self, bowner, bmid, kw):
    acquired = threading.enter_callback()
    try:
        return _block_callback(handle, argc, argv, cruby_self, bowner, bmid,
                               kw)
    finally:
        threading.leave_callback(acquired)


def _block_callback(handle, argc, argv, cruby_self, bowner, bmid, kw):
    """Called from C; no RPython exception may escape into libruby."""
    if blocks.error is not None or blocks.exc is not None \
            or blocks.jump is not None:
        return boot.as_value(value.Q_NIL)
    w_block = blocks.table[handle]
    if w_block is None:
        blocks.error = UnsupportedOperation(
            'a block was called after its handle was released')
        return boot.as_value(value.Q_NIL)
    args = boot.read_values(argv, argc)
    # A -1 cfunc frame gets keywords as a trailing Hash; only this flags it.
    kw_splat = boot.as_int(kw) != 0 and len(args) > 0
    # Run as a bmethod the proc IS the method; super needs that identity.
    override = _bmethod_identity(boot.as_signed(bowner),
                                 boot.as_signed(bmid), w_block)
    foreign = _enter_foreign_stack()
    try:
        # A registered bmethod runs as its own method, exactly as the native
        # dispatch runs it; the handle's block is not the lambda-flagged body.
        if override is not None and override.w_block is not None \
                and override.w_block.is_lambda:
            return boot.as_value(_run_bmethod(
                override, _sub_self(handle, cruby_self), args,
                NO_KEYWORDS, kw_splat))
        # CRuby owns the frame, so the block keeps its written cref.
        return boot.as_value(call_block(w_block, args, NO_KEYWORDS,
                                        kw_splat,
                                        _sub_self(handle, cruby_self),
                                        None, override))
    except RubyException, e:
        if debug.state.channels & debug.SUMMARY:
            debug.note('Ractor block raised RubyException')
        # A kill goes back to CRuby as the fatal it was; ensures have run.
        boot.rethrow_if_fiber_kill(e.value)
        # Held: the RPython field it waits in is not something CRuby scans.
        gcroots.hold(e.value)
        blocks.exc = e
        return _park_unwind()
    except block_mod.ForeignTag:
        # A tag CRuby owns; the shim re-issues it once our frames are gone.
        return _park_jumptag()
    except block_mod.BlockJump, e:
        if debug.state.channels & debug.SUMMARY:
            debug.note('Ractor block raised BlockJump')
        gcroots.hold(e.value)
        blocks.jump = e
        return _park_unwind()
    except RPyYarvError, e:
        if debug.state.channels & debug.SUMMARY:
            debug.note('Ractor block failed: %s' % e.msg)
        blocks.error = e
        return _park_unwind()
    except StackOverflow:
        if debug.state.channels & debug.SUMMARY:
            debug.note('Ractor block hit StackOverflow')
        # Returning normally would let CRuby re-call on an exhausted stack.
        debug.dump_frames('block')
        check_stack_overflow()
        blocks.error = UnsupportedOperation(STACK_TOO_DEEP)
        return _park_unwind()
    finally:
        if foreign:
            _leave_foreign_stack()


STACK_TOO_DEEP = 'the call is nested too deeply for RPyYARV\'s stack'


@dont_look_inside
def _park_jumptag():
    boot.set_block_jumptag()
    return boot.as_value(value.Q_NIL)


@dont_look_inside
def _park_unwind():
    """An RPython exception cannot cross libruby: the shim raises for it."""
    boot.set_block_unwind()
    return boot.as_value(value.Q_NIL)


TRAMP_OK = 0


TRAMP_RAISE = 1


TRAMP_UNSUPPORTED = 2


TRAMP_UNWIND = 3


# A tag a yield caught for a frame past ours; the shim re-issues it.
TRAMP_JUMPTAG = 4


def trampoline_callback(self_v, rid, owner_v, def_v, argc, argv, blockv, kw,
                        statusp, errp):
    acquired = threading.enter_callback()
    try:
        return _trampoline_callback(self_v, rid, owner_v, def_v, argc, argv,
                                    blockv, kw, statusp, errp)
    finally:
        threading.leave_callback(acquired)


def _trampoline_callback(self_v, rid, owner_v, def_v, argc, argv, blockv, kw,
                         statusp, errp):
    """Called from C; failures leave via statusp/errp, never into libruby."""
    boot.store_int(statusp, TRAMP_OK)
    boot.store_value(errp, value.Q_NIL)
    recv = boot.as_signed(self_v)
    # The def CRuby dispatched: exact across alias/define_method copies.
    from_def = dispatch.lookup_from_def(boot.as_signed(def_v))
    entry = None
    mid = rubycall.NO_MID
    owner = boot.as_signed(owner_v)
    if from_def is not None:
        mid = rubycall.mid_of_rid(boot.as_signed(rid))
        if mid == rubycall.NO_MID:
            # Interned so the identity check below never flies blind.
            mid = rubycall.intern_rid(boot.as_signed(rid))
        if mid != from_def.mid:
            # A recycled def address: the name disagrees, the map lies.
            from_def = None
        elif owner == value.Q_NIL or owner == 0 or owner == from_def.owner:
            entry = from_def
        # Same name, other owner: a copied def is legit, a recycled address
        # is not. The owner lookup below decides; from_def stays the net.
    if entry is None:
        # From the owner CRuby chose: super/bind_call name an ancestor, and
        # re-deriving from self's class would loop back to the most derived.
        if owner == value.Q_NIL or owner == 0:
            owner = value.class_of(recv)
        mid, entry = dispatch.lookup_from_trampoline(boot.as_signed(rid),
                                                     owner)
        if entry is None and owner != value.class_of(recv):
            # Aliases and the like keep the old dynamic resolution as a net.
            mid, entry = dispatch.lookup_from_trampoline(boot.as_signed(rid),
                                                         value.class_of(recv))
        if entry is None and from_def is not None:
            # The shared def is the best identity the maps still hold.
            mid = from_def.mid
            entry = from_def
    # argv lives on CRuby's VM stack for the call, so it needs no root.
    w_block = None
    proc_v = boot.as_signed(blockv)
    if proc_v != value.Q_NIL:
        # The depth here names this frame: a yield at the same depth is still
        # inside it, so it can reach CRuby's own block instead of the copy.
        w_block = block_mod.from_proc(proc_v, boot.nesting_depth())
    foreign = _enter_foreign_stack()
    try:
        return boot.as_value(_from_cruby(recv, mid, entry, argv,
                                         boot.as_int(argc), w_block,
                                         boot.as_int(kw) != 0))
    except block_mod.BlockBreak, e:
        # rb_iter_break from CRuby's own block: this call is what it ends.
        if e.w_block is not w_block:
            raise
        return boot.as_value(e.value)
    except block_mod.ForeignTag:
        # A return/throw aimed past us; the shim finishes the jump.
        boot.store_int(statusp, TRAMP_JUMPTAG)
    except RubyException, e:
        boot.rethrow_if_fiber_kill(e.value)
        boot.store_int(statusp, TRAMP_RAISE)
        boot.store_value(errp, e.value)
    except block_mod.BlockJump, e:
        # Aimed past this call: the shim raises so libruby unwinds its frames.
        gcroots.hold(e.value)
        blocks.jump = e
        boot.store_int(statusp, TRAMP_UNWIND)
    except block_mod.BlockNext:
        _tramp_failed(statusp, errp,
                      'next out of a method RPyYARV ran for CRuby is not '
                      'supported')
    except boot.RubyError, e:
        _tramp_failed(statusp, errp, "a call to '%s' failed" % e.mid)
    except RPyYarvError, e:
        _tramp_failed(statusp, errp, e.msg)
    except StackOverflow:
        debug.dump_frames('trampoline')
        check_stack_overflow()
        _tramp_failed(statusp, errp, STACK_TOO_DEEP)
    finally:
        if foreign:
            _leave_foreign_stack()
    return boot.as_value(value.Q_NIL)


class _Foreign(object):
    def __init__(self):
        self.depth = 0


foreign_stack = _Foreign()


@dont_look_inside
def _enter_foreign_stack():
    """A Fiber's stack is unmeasured, so the depth check is off here."""
    # Every C callback is outside the standalone entry stack. Nested entries
    # share one critical section; runaway recursion still needs rstack support.
    if boot.foreign_depth() == 0:
        unchecked_stack_start()
    boot.enter_foreign_depth()
    return True


@dont_look_inside
def _leave_foreign_stack():
    if boot.leave_foreign_depth() == 0:
        unchecked_stack_stop()


@dont_look_inside
def _tramp_failed(statusp, errp, msg):
    boot.store_int(statusp, TRAMP_UNSUPPORTED)
    boot.store_value(errp, boot.str_new('[rpyyarv] %s' % msg))


def _from_cruby(recv, mid, entry, argv, argc, w_block, kw_splat=False):
    """The trampoline's send half; argv/argc are CRuby's raw buffer, unread."""
    if mid == rubycall.NO_MID:
        raise UnsupportedOperation(
            'CRuby dispatched a method name RPyYARV never interned')
    if entry is None:
        raise UnsupportedOperation(
            "CRuby dispatched '%s' to RPyYARV, which no longer defines it"
            % symbols.name_of(mid))
    if entry.kind != dispatch.KIND_ISEQ:
        return _attr_from_cruby(entry, recv, boot.read_values(argv, argc),
                                w_block)
    callee_iseq = entry.w_iseq
    callee = Frame(callee_iseq, recv, None, entry)
    callee.block = w_block
    pc = 0
    if callee_iseq.simple_params and not kw_splat:
        if argc != callee_iseq.nparams:
            _arity_error(argc, callee_iseq.nparams, callee_iseq.nparams)
        # Simple params: argv's slots land straight in the callee's locals.
        i = 0
        while i < argc:
            callee.local_set(i, boot.read_value_at(argv, i))
            i += 1
    else:
        _refuse_iseq(callee_iseq, mid)
        pc = setup_params(callee_iseq, callee, boot.read_values(argv, argc),
                          False, NO_KEYWORDS, kw_splat)
    debug.count_native()
    return execute(callee_iseq, callee, pc)


def _attr_from_cruby(entry, recv, args, w_block=None):
    """_from_cruby's accessor case; CRuby's argv is already a marked buffer."""
    if entry.kind == dispatch.KIND_BMETHOD:
        debug.count_native()
        return _run_bmethod(entry, recv, args, NO_KEYWORDS, False, w_block)
    if entry.kind == dispatch.KIND_ATTR_READER:
        if len(args) != 0:
            _arity_error(len(args), 0, 0)
        debug.count_native()
        return dispatch.ivar_get(recv, entry.ivar)
    if len(args) != 1:
        _arity_error(len(args), 1, 1)
    dispatch.ivar_set(recv, entry.ivar, args[0])
    debug.count_native()
    return args[0]


@dont_look_inside
def _call_with_block(recv, mid, args, w_block, kw=False):
    if w_block.kind == block_mod.KIND_PROC:
        # Already a Proc: handed over as itself, it keeps module_eval's cref.
        try:
            return rubycall.call_with_proc(recv, mid, args,
                                           w_block.proc_value, kw)
        except boot.ForeignJump:
            raise block_mod.ForeignTag()
    handle = _alloc_handle(w_block)
    # No release: the handle's owner dies with the ifunc, freeing the slot.
    try:
        # A &:sym block has neither ISeq nor frame; the shim takes a null one.
        written = None
        native = 0
        if w_block.frame is not None:
            written = w_block.frame.cref
            if written is None and w_block.frame.entry is not None:
                written = w_block.frame.entry.lexical
        if w_block.w_iseq is not None:
            native = w_block.w_iseq.native
        ret = rubycall.call_with_block(
            recv, mid, args, handle, native,
            boot.native_cref(written), kw)
    except RubyException:
        # Whatever the block parked is the reason, and takes precedence.
        _check_block_error()
        raise
    _check_block_error()
    return ret


def _check_block_error():
    """Raises what a callback could not raise through libruby's frames."""
    exc = blocks.exc
    if exc is not None:
        blocks.exc = None
        gcroots.release(exc.value)
        raise exc
    jump = blocks.jump
    if jump is not None:
        blocks.jump = None
        gcroots.release(jump.value)
        raise jump
    err = blocks.error
    if err is not None:
        blocks.error = None
        raise err


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.defs import _bmethod_identity
from rpyyarv.interp.blocks import _alloc_handle, _run_bmethod, blocks, call_block
from rpyyarv.interp.execute import execute
