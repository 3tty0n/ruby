"""The interpreter loop and its JIT plumbing."""
from __future__ import absolute_import

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import dispatch
from rpyyarv import gcroots
from rpyyarv import helpers
from rpyyarv import insns
from rpyyarv import optable
import os
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RubyException, UnsupportedOperation
from rpyyarv.frame import Frame, PENDING_BREAK, PENDING_NEXT, PENDING_RAISE, PENDING_RETURN
from rpyyarv.iseq import NO_BLOCK_ISEQ
from rpyyarv.rlib import JitDriver, set_user_param

from rpyyarv.interp.consts_ids import ALLOCATE, DUP, EACH_SLICE, EACH_WITH_INDEX, EVAL, FORCE_ENCODING, GETBYTE, MATCH, SEND, SEND2, SETBYTE, STEP, SUCC, UNPACK1
from rpyyarv.interp.cref import _cref_of

PROXY_NAME = '__rpyyarv_block_param_proxy__'


def configure_jitparams():
    """RPYYARV_JITPARAM tunes the JIT as pypy's --jit does, no translation."""
    spec = os.environ.get('RPYYARV_JITPARAM')
    # function_threshold=100: Ruby methods go hot before a backedge does.
    # Eager bridges: branchy code (rubykon MCTS) needs them anyway.
    # No retrace_limit/max_retrace_guards: they segfault force_op_from_preamble.
    set_user_param(jitdriver, spec if spec else
                   'function_threshold=100,trace_eagerness=50')


def install():
    configure_reselection()
    configure_jitparams()
    boot.rb_patch_method_equality()
    boot.install_block_callback(block_callback)
    boot.install_trampoline_callback(trampoline_callback)
    gcroots.register_blocks(blocks)
    # A Symbol, so it is an immediate no mark hook has to reach.
    proxy.value = boot.sym_new(PROXY_NAME)
    fiber_kill.value = boot.fiber_killed_value()
    # Asked before any Ruby code runs, so these are the pristine owners.
    send_owners.kernel = dispatch.owner_of(
        value.core_class(value.C_OBJECT), SEND)
    helpers.modules.kernel = send_owners.kernel
    send_owners.basic = dispatch.owner_of(
        value.core_class(value.C_BASIC_OBJECT), SEND2)
    send_owners.eval = dispatch.owner_of(
        value.core_class(value.C_OBJECT), EVAL)
    send_owners.string_getbyte = dispatch.owner_of(
        value.core_class(value.C_STRING), GETBYTE)
    send_owners.string_setbyte = dispatch.owner_of(
        value.core_class(value.C_STRING), SETBYTE)
    send_owners.array_each_slice = dispatch.owner_of(
        value.core_class(value.C_ARRAY), EACH_SLICE)
    send_owners.array_each_with_index = dispatch.owner_of(
        value.core_class(value.C_ARRAY), EACH_WITH_INDEX)
    send_owners.integer_step = dispatch.owner_of(
        value.core_class(value.C_INTEGER), STEP)
    send_owners.class_allocate = dispatch.owner_of(
        value.core_class(value.C_CLASS), ALLOCATE)
    send_owners.string_force_encoding = dispatch.owner_of(
        value.core_class(value.C_STRING), FORCE_ENCODING)
    send_owners.string_unpack1 = dispatch.owner_of(
        value.core_class(value.C_STRING), UNPACK1)
    send_owners.array_pack = dispatch.owner_of(
        value.core_class(value.C_ARRAY), helpers.PACK)
    send_owners.comparable = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Comparable'))
    encodings.value = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Encoding'))
    regexp_class.value = dispatch.const_get(
        value.core_class(value.C_OBJECT), symbols.intern('Regexp'))


def _binop(frame, recv, arg, mid):
    """Both operands back on the marked stack before the send allocates."""
    frame.push(recv)
    frame.push(arg)
    return _opt_send(frame, mid, 1)


def _unop(frame, recv, mid):
    frame.push(recv)
    return _opt_send(frame, mid, 0)


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


# is_recursive: a portal call at an inlining limit escapes the virtualizable.
jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'], is_recursive=True,
                      get_printable_location=get_printable_location)


class _Reselection(object):
    """One deliberate reselection: the first traces come off a cold profile."""
    # Quasi-immutable, so disabling folds the counter below out of every trace.
    _immutable_fields_ = ['enabled?']

    def __init__(self):
        self.enabled = True
        self.count = 0
        self.at = RESELECT_AT


# Late enough for a warm profile, early enough to still be measured.
RESELECT_AT = 2000000


reselection = _Reselection()


def configure_reselection():
    """RPYYARV_RESELECT_AT sets the backedge count to reselect at; 0 off."""
    spec = os.environ.get('RPYYARV_RESELECT_AT')
    if spec is None:
        return
    try:
        at = int(spec)
    except ValueError:
        return
    reselection.at = at
    reselection.enabled = at > 0


def _tick_reselection():
    if reselection.enabled:
        reselection.count += 1
        if reselection.count > reselection.at:
            # Disabling invalidates every trace, which is the reselection.
            reselection.enabled = False


def _epc(iseq, pc):
    """Catch-table ranges are against the pc *after* the raising instruction."""
    return pc + 1 + optable.NUM_OPERANDS[iseq.code[pc]]


def execute(iseq, frame, pc=0):
    """Two shapes: the handler shape stops the JIT inlining; iseq is green."""
    if iseq.catches_return:
        return _execute_returnable(iseq, frame, pc)
    if len(iseq.catches) == 0:
        gcroots.push_frame(frame)
        try:
            return _execute(iseq, frame, pc)
        finally:
            gcroots.pop_frame(frame)
    return _execute_guarded(iseq, frame, pc)


def _execute_returnable(iseq, frame, pc):
    """A frame a `return` in one of its blocks names (valid_return)."""
    try:
        try:
            if len(iseq.catches) == 0:
                gcroots.push_frame(frame)
                try:
                    return _execute(iseq, frame, pc)
                finally:
                    gcroots.pop_frame(frame)
            return _execute_guarded(iseq, frame, pc)
        except block_mod.BlockReturn, e:
            if e.frame is not frame:
                raise
            return e.value
    finally:
        frame.dead = True


def _execute_guarded(iseq, frame, pc):
    # No loop: it would stop the tracer inlining this and abort the trace.
    gcroots.push_frame(frame)
    try:
        try:
            return _execute(iseq, frame, pc)
        except RubyException, e:
            throw = Throw(PENDING_RAISE, e.value, None, e.name)
        except block_mod.BlockBreak, e:
            throw = Throw(PENDING_BREAK, e.value, e.w_block)
        except block_mod.BlockReturn, e:
            throw = Throw(PENDING_RETURN, e.value, None, 'return', e.frame)
        except block_mod.BlockNext, e:
            throw = Throw(PENDING_NEXT, e.value)
        return _execute_unwinding(iseq, frame, throw)
    finally:
        gcroots.pop_frame(frame)


def _execute_unwinding(iseq, frame, throw):
    while True:
        pc = _unwind(iseq, frame, throw, _epc(iseq, frame.pc))
        try:
            return _execute(iseq, frame, pc)
        except RubyException, e:
            throw = Throw(PENDING_RAISE, e.value, None, e.name)
        except block_mod.BlockBreak, e:
            throw = Throw(PENDING_BREAK, e.value, e.w_block)
        except block_mod.BlockReturn, e:
            throw = Throw(PENDING_RETURN, e.value, None, 'return', e.frame)
        except block_mod.BlockNext, e:
            throw = Throw(PENDING_NEXT, e.value)


def _execute(iseq, frame, pc):
    while True:
        jitdriver.jit_merge_point(iseq=iseq, pc=pc, frame=frame)
        # Only an unwinding exception reads this; the store is free in a trace.
        frame.pc = pc
        # Rebound each iteration: hoisting leaves a live non-green, non-red var.
        code = iseq.code
        opcode = code[pc]
        if debug.state.enabled:
            debug.trace_insn(iseq, pc, frame)
        pc += 1

        if opcode == insns.NOP:
            pass
        elif opcode == insns.PUTNIL:
            frame.push(value.Q_NIL)
        elif opcode == insns.PUTSELF:
            frame.push(frame.self_val)
        elif opcode == insns.PUTOBJECT:
            idx = code[pc]
            pc += 1
            frame.push(iseq.consts[idx])
        elif opcode == insns.PUTSTRING or opcode == insns.PUTCHILLEDSTRING:
            idx = code[pc]
            pc += 1
            # A literal is a fresh String on every evaluation in Ruby.
            frame.push(rubycall.call0(iseq.consts[idx], DUP))
        elif opcode == insns.GETLOCAL:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            if packed == idx:
                frame.push(frame.local_get(idx))
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                frame.push(_outer_frame(frame, level).local_get(idx))
        elif opcode == insns.SETLOCAL:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            if packed == idx:
                frame.local_set(idx, frame.pop())
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                _outer_frame(frame, level).local_set(idx, frame.pop())
        elif opcode == insns.GETBLOCKPARAMPROXY:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            if f.block_param_set:
                frame.push(f.local_get(idx))
            elif f.block is None:
                frame.push(value.Q_NIL)
            else:
                frame.push(proxy.value)
        elif opcode == insns.GETBLOCKPARAM:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            if not f.block_param_set:
                f.local_set(idx, _to_proc(f.block))
                f.block_param_set = True
            frame.push(f.local_get(idx))
        elif opcode == insns.SETBLOCKPARAM:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            f = _local_frame(frame, packed)
            f.local_set(idx, frame.pop())
            f.block_param_set = True
        elif opcode == insns.DUP:
            v = frame.pop()
            frame.push(v)
            frame.push(v)
        elif opcode == insns.POP:
            frame.pop()
        elif opcode == insns.SWAP:
            a = frame.pop()
            b = frame.pop()
            frame.push(a)
            frame.push(b)
        elif opcode == insns.EXPANDARRAY:
            n = code[pc]
            flag = code[pc + 1]
            pc += 2
            _expand(frame, frame.pop(), n, flag)
        elif opcode == insns.OPT_PLUS:
            b = frame.pop()
            a = frame.pop()
            v = helpers.add(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.PLUS))
        elif opcode == insns.OPT_MINUS:
            b = frame.pop()
            a = frame.pop()
            v = helpers.sub(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.MINUS))
        elif opcode == insns.OPT_MULT:
            b = frame.pop()
            a = frame.pop()
            v = helpers.mul(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.MULT))
        elif opcode == insns.OPT_LT:
            b = frame.pop()
            a = frame.pop()
            v = helpers.lt(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.LT))
        elif opcode == insns.OPT_GT:
            b = frame.pop()
            a = frame.pop()
            v = helpers.gt(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.GT))
        elif opcode == insns.OPT_LE:
            b = frame.pop()
            a = frame.pop()
            v = helpers.le(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.LE))
        elif opcode == insns.OPT_GE:
            b = frame.pop()
            a = frame.pop()
            v = helpers.ge(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.GE))
        elif opcode == insns.OPT_EQ:
            b = frame.pop()
            a = frame.pop()
            v = helpers.eq(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.EQ))
        elif opcode == insns.OBJTOSTRING:
            frame.push(_to_s(frame.pop()))
        elif opcode == insns.ANYTOSTRING:
            v_str = frame.pop()
            v_val = frame.pop()
            if not rubycall.is_string(v_str):
                raise UnsupportedOperation('to_s on %s did not return a String'
                                           % value.repr_of(v_val))
            frame.push(v_str)
        elif opcode == insns.CONCATSTRINGS:
            n = code[pc]
            pc += 1
            parts = [0] * n
            i = n - 1
            while i >= 0:
                parts[i] = frame.pop()
                i -= 1
            frame.push(_concat(parts))
        elif opcode == insns.TOREGEXP:
            opt = code[pc]
            n = code[pc + 1]
            pc += 2
            at = frame.sp - n
            if at < 0:
                raise UnsupportedOperation(
                    'toregexp with %d part(s) underflows the stack' % n)
            parts = [0] * n
            i = 0
            while i < n:
                parts[i] = frame.stack[at + i]
                i += 1
            regexp = boot.toregexp(opt, parts)
            _drop(frame, at)
            frame.push(regexp)
        elif opcode == insns.INTERN:
            frame.push(boot.str_intern(frame.pop()))
        elif opcode == insns.OPT_DIV:
            b = frame.pop()
            a = frame.pop()
            v = helpers.div(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.DIV))
        elif opcode == insns.OPT_MOD:
            b = frame.pop()
            a = frame.pop()
            v = helpers.mod(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.MOD))
        elif opcode == insns.OPT_NEQ:
            b = frame.pop()
            a = frame.pop()
            v = helpers.neq(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.NEQ))
        elif opcode == insns.GETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            frame.push(dispatch.ivar_get(frame.self_val, mid))
        elif opcode == insns.SETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            dispatch.ivar_set(frame.self_val, mid, frame.pop())
        elif opcode == insns.ONCE:
            idx = code[pc]
            pc += 1
            v = iseq.once_cache[idx]
            if v == value.Q_UNDEF:
                v = _run_once(frame, iseq, idx)
            frame.push(v)
        elif opcode == insns.GETCLASSVARIABLE:
            mid = code[pc]
            pc += 1
            frame.push(_cvar_get(_cref_of(frame), mid))
        elif opcode == insns.SETCLASSVARIABLE:
            mid = code[pc]
            pc += 1
            _cvar_set(_cref_of(frame), mid, frame.pop())
        elif opcode == insns.DEFINED:
            kind = code[pc]
            obj = iseq.consts[code[pc + 1]]
            pushval = iseq.consts[code[pc + 2]]
            pc += 3
            recv = frame.pop()
            frame.push(pushval if _defined(frame, kind, obj, recv)
                       else value.Q_NIL)
        elif opcode == insns.DEFINEDIVAR:
            mid = code[pc]
            pushval = iseq.consts[code[pc + 1]]
            pc += 2
            frame.push(pushval if boot.ivar_defined(
                frame.self_val, rubycall.rid(mid)) else value.Q_NIL)
        elif opcode == insns.GETCONSTANT:
            mid = code[pc]
            pc += 1
            allow_nil = frame.pop()
            cbase = frame.pop()
            if allow_nil == value.Q_TRUE and cbase == value.Q_NIL:
                frame.push(_const_lexical(_cref_of(frame), mid))
            else:
                frame.push(dispatch.const_get(cbase, mid))
        elif opcode == insns.PUTSPECIALOBJECT:
            kind = code[pc]
            pc += 1
            if kind == optable.SPECIAL_OBJECT_VMCORE:
                frame.push(_vm_core())
            elif kind == optable.SPECIAL_OBJECT_CBASE:
                # vm_get_cbase: an eval-pushed cref counts, unlike CONST_BASE.
                frame.push(_cbase(frame))
            else:
                frame.push(_const_base(frame))
        elif opcode == insns.OPT_GETCONSTANT_PATH:
            idx = code[pc]
            pc += 1
            frame.push(_const_path(frame, iseq, idx))
        elif opcode == insns.SETCONSTANT:
            mid = code[pc]
            pc += 1
            cbase = frame.pop()
            dispatch.const_set(cbase, mid, frame.pop())
        elif opcode == insns.DEFINECLASS:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            flags = code[pc + 2]
            pc += 3
            super_v = frame.pop()
            cbase = frame.pop()
            if not flags & optable.DEFINECLASS_FLAG_HAS_SUPERCLASS:
                super_v = 0
            kind = flags & optable.DEFINECLASS_TYPE_MASK
            if kind == optable.DEFINECLASS_TYPE_SINGLETON_CLASS:
                frame.push(_definesingletonclass(frame, w_body, cbase))
            else:
                frame.push(_defineclass(
                    frame, mid, w_body, cbase, super_v,
                    kind == optable.DEFINECLASS_TYPE_MODULE))
        elif opcode == insns.OPT_NEW:
            w_ci = iseq.callinfos[code[pc]]
            target = code[pc + 1]
            pc += 2
            at = frame.sp - w_ci.argc - 1
            below = at - 1
            if below < 0:
                raise UnsupportedOperation(
                    'opt_new with %d argument(s) underflows the stack'
                    % w_ci.argc)
            assert at >= 1
            assert below >= 0
            obj = _opt_new_alloc(frame.stack[at])
            if obj == 0:
                pc = target
            else:
                # Receiver of the initialize send; below it, that send's result.
                frame.stack[at] = obj
                frame.stack[below] = obj
        elif opcode == insns.DEFINEMETHOD:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            pc += 2
            define_method(frame, mid, w_body)
        elif opcode == insns.DEFINESMETHOD:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            pc += 2
            dispatch.define_singleton(frame.pop(), mid, w_body,
                                      _const_base(frame), _cref_of(frame))
        elif opcode == insns.OPT_SEND_WITHOUT_BLOCK:
            idx = code[pc]
            pc += 1
            frame.push(invoke(frame, iseq.callinfos[idx]))
        elif opcode == insns.SEND:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            w_ci = iseq.callinfos[idx]
            w_block = None
            if block != NO_BLOCK_ISEQ:
                w_block = block_mod.W_Block(iseq.iseqs[block], frame,
                                            frame.block)
            frame.push(invoke(frame, w_ci, w_block))
        elif opcode == insns.INVOKEBLOCK:
            idx = code[pc]
            pc += 1
            frame.push(invoke_block(frame, iseq.callinfos[idx]))
        elif opcode == insns.SENDFORWARD:
            idx = code[pc]
            pc += 2
            w_ci = iseq.callinfos[idx]
            at = frame.sp - 1 - w_ci.argc
            assert at >= 0
            # The frame's own block rides along, as a bare super forwards it.
            frame.push(_splat_invoke(frame, w_ci, at, w_ci.argc, frame.block,
                                     w_ci.mid, w_ci.fcall))
        elif opcode == insns.INVOKESUPERFORWARD:
            idx = code[pc]
            pc += 2
            frame.push(invoke_super(frame, iseq.callinfos[idx]))
        elif opcode == insns.INVOKESUPER:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            if block != NO_BLOCK_ISEQ:
                w_blk = block_mod.W_Block(iseq.iseqs[block], frame,
                                          frame.block)
                frame.push(invoke_super(frame, iseq.callinfos[idx], w_blk,
                                        True))
            else:
                frame.push(invoke_super(frame, iseq.callinfos[idx]))
        elif opcode == insns.JUMP:
            target = code[pc]
            pc += 1
            backward = target < pc
            pc = target
            if backward:
                _tick_reselection()
                jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHIF:
            target = code[pc]
            pc += 1
            if value.is_true(frame.pop()):
                backward = target < pc
                pc = target
                if backward:
                    _tick_reselection()
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHUNLESS:
            target = code[pc]
            pc += 1
            if not value.is_true(frame.pop()):
                backward = target < pc
                pc = target
                if backward:
                    _tick_reselection()
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHNIL:
            target = code[pc]
            pc += 1
            if frame.pop() == value.Q_NIL:
                backward = target < pc
                pc = target
                if backward:
                    _tick_reselection()
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.CHECKMATCH:
            flag = code[pc]
            pc += 1
            pattern = frame.pop()
            target = frame.pop()
            frame.push(_checkmatch(target, pattern, flag))
        elif opcode == insns.CHECKKEYWORD:
            idx = code[pc]
            bit = code[pc + 1]
            pc += 2
            assert idx >= 0
            # A set bit means unfilled, so the body computes the default.
            frame.push(value.newbool(
                (value.fix2int(frame.local_get(idx)) & (1 << bit)) == 0))
        elif opcode == insns.THROW:
            throw_state = code[pc]
            pc += 1
            _throw(frame, throw_state, frame.pop())
        elif opcode == insns.LEAVE:
            return frame.pop()
        elif opcode == insns.SETN:
            n = code[pc]
            pc += 1
            at = frame.sp - 1 - n
            top = frame.sp - 1
            if at < 0:
                raise UnsupportedOperation('setn %d underflows the stack' % n)
            assert top >= 0
            frame.stack[at] = frame.stack[top]
        elif opcode == insns.TOPN:
            n = code[pc]
            pc += 1
            at = frame.sp - 1 - n
            if at < 0:
                raise UnsupportedOperation('topn %d underflows the stack' % n)
            frame.push(frame.stack[at])
        elif opcode == insns.DUPN:
            n = code[pc]
            pc += 1
            _dupn(frame, n)
        elif opcode == insns.ADJUSTSTACK:
            n = code[pc]
            pc += 1
            _adjuststack(frame, n)
        elif opcode == insns.OPT_REVERSE:
            n = code[pc]
            pc += 1
            _reverse(frame, n)
        elif opcode == insns.NEWARRAY:
            n = code[pc]
            pc += 1
            frame.push(_newarray(frame, n))
        elif opcode == insns.DUPARRAY:
            idx = code[pc]
            pc += 1
            # The literal in the pool is shared; every evaluation gets a copy.
            frame.push(rubycall.ary_resurrect(iseq.consts[idx]))
        elif opcode == insns.NEWHASH:
            n = code[pc]
            pc += 1
            frame.push(_newhash(frame, n))
        elif opcode == insns.DUPHASH:
            idx = code[pc]
            pc += 1
            frame.push(rubycall.hash_resurrect(iseq.consts[idx]))
        elif opcode == insns.SPLATARRAY:
            idx = code[pc]
            pc += 1
            flag = value.is_true(iseq.consts[idx])
            frame.push(rubycall.splat_array(frame.pop(), flag))
        elif opcode == insns.OPT_AND:
            b = frame.pop()
            a = frame.pop()
            v = helpers.and_(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.AND))
        elif opcode == insns.OPT_OR:
            b = frame.pop()
            a = frame.pop()
            v = helpers.or_(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.OR))
        elif opcode == insns.NEWRANGE:
            flag = code[pc]
            pc += 1
            high = frame.pop()
            low = frame.pop()
            frame.push(rubycall.range_new(low, high, flag))
        elif opcode == insns.GETGLOBAL:
            mid = code[pc]
            pc += 1
            frame.push(rubycall.gvar_get(mid))
        elif opcode == insns.SETGLOBAL:
            mid = code[pc]
            pc += 1
            rubycall.gvar_set(mid, frame.pop())
        elif opcode == insns.GETSPECIAL:
            key = code[pc]
            type = code[pc + 1]
            pc += 2
            assert key == 1
            frame.push(boot.getspecial(type))
        elif opcode == insns.OPT_AREF:
            idx = frame.pop()
            recv = frame.pop()
            v = helpers.aref(recv, idx)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, recv, idx, helpers.AREF))
        elif opcode == insns.OPT_ASET:
            val = frame.pop()
            idx = frame.pop()
            recv = frame.pop()
            v = helpers.aset(recv, idx, val)
            if v == value.Q_UNDEF:
                frame.push(recv)
                frame.push(idx)
                frame.push(val)
                v = _opt_send(frame, helpers.ASET, 2)
            frame.push(v)
        elif opcode == insns.OPT_LENGTH:
            recv = frame.pop()
            v = helpers.length(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.LENGTH))
        elif opcode == insns.OPT_SIZE:
            recv = frame.pop()
            v = helpers.size(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.SIZE))
        elif opcode == insns.OPT_EMPTY_P:
            recv = frame.pop()
            v = helpers.empty_p(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.EMPTY_P))
        elif opcode == insns.OPT_NOT:
            frame.push(helpers.opt_not(frame.pop()))
        elif opcode == insns.OPT_LTLT:
            b = frame.pop()
            a = frame.pop()
            v = helpers.lshift(a, b)
            frame.push(v if v != value.Q_UNDEF
                       else _binop(frame, a, b, helpers.LTLT))
        elif opcode == insns.OPT_NIL_P:
            recv = frame.pop()
            v = helpers.nil_p(recv)
            frame.push(v if v != value.Q_UNDEF
                       else _unop(frame, recv, helpers.NIL_P))
        elif opcode == insns.OPT_SUCC:
            recv = frame.pop()
            v = helpers.add(recv, value.int2fix(1))
            frame.push(v if v != value.Q_UNDEF else _unop(frame, recv, SUCC))
        elif opcode == insns.OPT_STR_FREEZE:
            idx = code[pc]
            pc += 1
            v_str = iseq.consts[idx]
            if helpers.str_freeze_pristine():
                frame.push(v_str)
            else:
                frame.push(_unop(frame, rubycall.call0(v_str, DUP),
                                 helpers.FREEZE))
        elif opcode == insns.OPT_STR_UMINUS:
            idx = code[pc]
            pc += 1
            v_str = iseq.consts[idx]
            v = helpers.str_uminus(v_str)
            if v != value.Q_UNDEF:
                frame.push(v)
            else:
                frame.push(_unop(frame, v_str, helpers.UMINUS))
        elif opcode == insns.OPT_ARY_FREEZE or \
                opcode == insns.OPT_HASH_FREEZE:
            idx = code[pc]
            pc += 1
            frame.push(_unop(frame, rubycall.call0(iseq.consts[idx], DUP),
                             helpers.FREEZE))
        elif opcode == insns.OPT_CASE_DISPATCH:
            table = code[pc]
            else_pc = code[pc + 1]
            pc += 2
            key = frame.pop()
            if value.is_fixnum(key) and helpers.int_eqq_pristine():
                target = iseq.case_tables[table].get(value.fix2int(key), -1)
                pc = else_pc if target < 0 else target
        elif opcode == insns.OPT_NEWARRAY_SEND:
            n = code[pc]
            meth = code[pc + 1]
            pc += 2
            frame.push(_newarray_send(frame, n, meth))
        elif opcode == insns.PUSHTOARRAY:
            n = code[pc]
            pc += 1
            _pushtoarray(frame, n)
        elif opcode == insns.CONCATARRAY or opcode == insns.CONCATTOARRAY:
            b = frame.pop()
            a = frame.pop()
            frame.push(rubycall.concat_array(
                a, b, opcode == insns.CONCATTOARRAY))
        elif opcode == insns.OPT_REGEXPMATCH2:
            b = frame.pop()
            a = frame.pop()
            frame.push(_binop(frame, a, b, MATCH))
        elif opcode == insns.SPLATKW:
            block_v = frame.pop()
            hash_v = frame.pop()
            frame.push(value.Q_NIL if hash_v == value.Q_NIL
                       else rubycall.to_hash_type(hash_v))
            frame.push(block_v)
        elif opcode == insns.OPT_DUPARRAY_SEND:
            idx = code[pc]
            mid = code[pc + 1]
            pc += 3
            arg = frame.pop()
            frame.push(rubycall.call1(
                rubycall.ary_resurrect(iseq.consts[idx]), mid, arg))
        else:
            raise UnsupportedOperation(
                'unknown opcode %d in %s (%s) at pc %d'
                % (opcode, iseq.name, iseq.path, pc))


def run(iseq):
    debug.dump_iseq(iseq)
    ret = execute(iseq, Frame(iseq, boot.top_self()))
    debug.summary()
    return ret


def run_in_cruby():
    """The whole script handed back; its answer is the exit status."""
    return boot.run_node()


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.builtins import _vm_core, encodings, fiber_kill, proxy, regexp_class
from rpyyarv.interp.sends import _opt_send, _splat_invoke, invoke, send_owners
from rpyyarv.interp.supers import invoke_super
from rpyyarv.interp.defs import define_method
from rpyyarv.interp.blocks import _outer_frame, _to_proc, blocks, invoke_block
from rpyyarv.interp.callbacks import block_callback, trampoline_callback
from rpyyarv.interp.throws import Throw, _throw, _unwind
from rpyyarv.interp.stackops import _adjuststack, _concat, _drop, _dupn, _expand, _local_frame, _newarray, _newarray_send, _newhash, _pushtoarray, _reverse, _to_s
from rpyyarv.interp.consts import _cbase, _checkmatch, _const_base, _const_lexical, _const_path, _cvar_get, _cvar_set, _defineclass, _defined, _definesingletonclass, _opt_new_alloc, _run_once
