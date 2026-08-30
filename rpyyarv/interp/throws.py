"""Non-local exits: break, next, return, retry, raise."""
from __future__ import absolute_import

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import optable
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.dispatch.core import KIND_BMETHOD
from rpyyarv.error import RubyException, UnsupportedOperation, errinfos
from rpyyarv.frame import Frame, PENDING_BREAK, PENDING_FOREIGN, PENDING_NEXT, PENDING_NONE, PENDING_RAISE, PENDING_RETRY, PENDING_RETURN
from rpyyarv.iseq import CATCH_ENSURE, CATCH_RESCUE, CATCH_RETRY
from rpyyarv.rlib import dont_look_inside

class Throw(object):
    """A throw in flight; _rethrow turns it back into an exception."""
    def __init__(self, kind, value, w_block=None, name='raise',
                 target=None):
        self.kind = kind
        self.value = value
        self.w_block = w_block
        # PENDING_RETURN: the frame the return is aimed at.
        self.target = target
        self.name = name


def _rethrow(throw):
    if throw.kind == PENDING_RAISE:
        raise RubyException(throw.value, throw.name)
    if throw.kind == PENDING_BREAK:
        raise block_mod.BlockBreak(throw.w_block, throw.value)
    if throw.kind == PENDING_RETURN:
        raise block_mod.BlockReturn(throw.target, throw.value)
    if throw.kind == PENDING_RETRY:
        raise block_mod.BlockRetry()
    if throw.kind == PENDING_FOREIGN:
        raise block_mod.ForeignTag()
    raise block_mod.BlockNext(throw.value)


# A longer chain is corrupt; the walk must terminate for the tracer.
MAX_SCOPES = 256


def _owns_return(f):
    """A lambda, or a bmethod whose block IS the body (VM_FRAME_BMETHOD_P)."""
    w_block = f.own_block
    if w_block is None:
        return False
    if w_block.is_lambda:
        return True
    entry = f.entry
    return entry is not None and entry.kind == KIND_BMETHOD \
        and entry.w_block is w_block


def _return_target(frame):
    """Nearest lambda frame, else the outermost (vm_insnhelper.c:1834)."""
    f = frame
    n = 0
    while n < MAX_SCOPES:
        if _owns_return(f):
            return f
        if f.defining_frame is None:
            return f
        f = f.defining_frame
        n += 1
    return f


@dont_look_inside
def _local_jump_error(mesg, v, reason):
    return RubyException(boot.local_jump_error(mesg, v, reason), 'return')


def _return(frame, v):
    """return from a block; a dead target raises (vm_insnhelper.c:1926)."""
    target = _return_target(frame)
    if target.dead or not (target.w_iseq.catches_return
                           or _owns_return(target)):
        raise _local_jump_error('unexpected return', v, optable.TAG_RETURN)
    raise block_mod.BlockReturn(target, v)


def _throw(frame, throw_state, v):
    tag = throw_state & optable.TAG_MASK
    if tag == optable.TAG_NEXT:
        raise block_mod.BlockNext(v)
    if tag == optable.TAG_BREAK:
        w_block = frame.own_block
        if w_block is None:
            raise UnsupportedOperation('break outside a block')
        raise block_mod.BlockBreak(w_block, v)
    if tag == optable.TAG_RETURN:
        _return(frame, v)
    if tag == optable.TAG_NONE:
        # vm_throw_continue: re-raise what this catch ISeq runs under.
        if frame.pending_kind == PENDING_NONE:
            raise UnsupportedOperation(
                'throw 0 outside a rescue or ensure body')
        _rethrow(Throw(frame.pending_kind, frame.pending_value,
                       frame.pending_block, 'raise', frame.pending_frame))
    if tag == optable.TAG_RETRY:
        raise block_mod.BlockRetry()
    raise UnsupportedOperation(
        'throw with tag %d (redo) is not supported' % tag)


def _is_fiber_kill(throw):
    """Fiber#kill travels as a raise for ensures, but no rescue may take it."""
    return throw.kind == PENDING_RAISE and throw.value == fiber_kill.value \
        and fiber_kill.value != 0


def _catch_for(iseq, epc, kind, fatal=False):
    """First catch entry covering epc (vm.c:2911); break/next take ensure."""
    catches = iseq.catches
    i = 0
    while i < len(catches):
        entry = catches[i]
        if entry.start < epc and epc <= entry.end:
            if entry.kind == CATCH_ENSURE or \
                    (entry.kind == CATCH_RESCUE and kind == PENDING_RAISE
                     and not fatal) or \
                    (entry.kind == CATCH_RETRY and kind == PENDING_RETRY):
                return entry
        i += 1
    return None


def _run_catch(frame, entry, throw):
    """A catch ISeq's frame chains to the raiser's locals (vm.c:3014)."""
    w_iseq = entry.w_iseq
    callee = Frame(w_iseq, frame.self_val, frame.cref, frame.entry)
    callee.defining_frame = frame
    callee.block = frame.block
    callee.own_block = frame.own_block
    if w_iseq.nlocals > 0:
        # Local 0 is `$!`; for a break or a next nothing reads it.
        callee.local_set(0, throw.value if throw.kind == PENDING_RAISE
                         and not _is_fiber_kill(throw) else value.Q_NIL)
    callee.pending_kind = throw.kind
    callee.pending_value = throw.value
    callee.pending_block = throw.w_block
    callee.pending_frame = throw.target
    if throw.kind == PENDING_FOREIGN:
        # errinfo carries the parked tag's target, not an exception object.
        return execute(w_iseq, callee)
    return _run_with_errinfo(w_iseq, callee, callee.local_get(0)
                             if w_iseq.nlocals > 0 else value.Q_NIL)


def _run_with_errinfo(w_iseq, callee, errinfo):
    """$! reads ec->errinfo: RPyYARV pushes no CRuby rescue frame."""
    prev = rubycall.swap_errinfo(errinfo)
    # Taking the exception out of libruby cleared ec->errinfo, so the
    # enclosing rescue's own $! is what this body has to put back.
    if prev == value.Q_NIL and len(errinfos.stack) > 0:
        prev = errinfos.stack[len(errinfos.stack) - 1]
    errinfos.stack.append(errinfo)
    try:
        return execute(w_iseq, callee)
    finally:
        errinfos.stack.pop()
        rubycall.swap_errinfo(prev)


def _unwind(iseq, frame, throw, epc):
    """Run catch entries covering epc; answers the resume pc, or re-raises."""
    while True:
        entry = _catch_for(iseq, epc, throw.kind,
                           _is_fiber_kill(throw))
        if entry is None:
            _rethrow(throw)
        frame.reset_sp(entry.sp)
        if entry.kind == CATCH_RETRY:
            return entry.cont
        frame.pc = entry.cont
        try:
            result = _run_catch(frame, entry, throw)
        except RubyException, e:
            throw = Throw(PENDING_RAISE, e.value, None, e.name)
        except block_mod.BlockBreak, e:
            throw = Throw(PENDING_BREAK, e.value, e.w_block)
        except block_mod.BlockReturn, e:
            throw = Throw(PENDING_RETURN, e.value, None, 'return', e.frame)
        except block_mod.BlockNext, e:
            throw = Throw(PENDING_NEXT, e.value)
        except block_mod.BlockRetry:
            throw = Throw(PENDING_RETRY, value.Q_NIL)
        except block_mod.ForeignTag:
            throw = Throw(PENDING_FOREIGN, value.Q_NIL)
        else:
            frame.reset_sp(entry.sp)
            frame.push(result)
            return entry.cont
        # The catch ISeq threw in turn; cont is where the frame's pc stands.
        epc = entry.cont


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.builtins import fiber_kill
from rpyyarv.interp.execute import execute
