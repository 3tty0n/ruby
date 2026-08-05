import debug
import insns
import helpers
import symbols
from error import UnsupportedOperation
from frame import Frame
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from methods import W_CFunc, W_ISeqMethod
from objects.array import W_Array
from objects.string import W_String
from objects.transparent import w_nil
from rlib import JitDriver, unroll_safe


def _as_iseq(w_x):
    assert isinstance(w_x, W_ISeq)      # RPython downcast
    return w_x


def _callinfo(iseq, idx):
    w_ci = iseq.consts[idx]
    assert isinstance(w_ci, W_CallInfo)
    return w_ci


@unroll_safe
def invoke(frame, w_ci):
    argc = w_ci.argc
    recv_at = frame.sp - argc - 1
    if recv_at < 0:
        raise UnsupportedOperation(
            "call to '%s' with %d argument(s) underflows the stack"
            % (symbols.name_of(w_ci.mid), argc))
    if not w_ci.simple:
        raise UnsupportedOperation(
            "call to '%s' passes arguments RPyYARV does not support"
            % symbols.name_of(w_ci.mid))

    w_recv = frame.stack[recv_at]
    w_method = w_recv.lookup_method(w_ci.mid)
    if w_method.private and not w_ci.fcall:
        raise UnsupportedOperation("private method '%s' called for %s"
                                   % (symbols.name_of(w_ci.mid), w_recv.repr()))

    if isinstance(w_method, W_ISeqMethod):
        callee_iseq = w_method.w_iseq
        if not callee_iseq.simple_params:
            raise UnsupportedOperation(
                "method '%s' has parameters RPyYARV does not support"
                % symbols.name_of(w_ci.mid))
        _check_argc(w_ci.mid, argc, callee_iseq.nparams)
        callee = Frame(callee_iseq, w_recv)
        i = 0
        while i < argc:
            callee.locals[i] = frame.stack[recv_at + 1 + i]
            i += 1
        _drop(frame, recv_at)
        if not debug.state.enabled:
            return execute(callee_iseq, callee)
        traced_w = []
        i = 0
        while i < argc:
            traced_w.append(callee.locals[i])
            i += 1
        debug.trace_enter(w_ci.mid, traced_w)
        w_ret = execute(callee_iseq, callee)
        debug.trace_leave(w_ci.mid, w_ret)
        return w_ret

    assert isinstance(w_method, W_CFunc)
    if w_method.arity >= 0:
        _check_argc(w_ci.mid, argc, w_method.arity)
    args_w = []
    i = 0
    while i < argc:
        args_w.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    if not debug.state.enabled:
        return w_method.call(w_recv, args_w)
    debug.trace_enter(w_ci.mid, args_w)
    w_ret = w_method.call(w_recv, args_w)
    debug.trace_leave(w_ci.mid, w_ret)
    return w_ret


def call_method(w_method, w_recv, args_w):
    if isinstance(w_method, W_CFunc):
        if w_method.arity >= 0:
            _check_argc(w_method.mid, len(args_w), w_method.arity)
        return w_method.call(w_recv, args_w)

    assert isinstance(w_method, W_ISeqMethod)
    callee_iseq = w_method.w_iseq
    if not callee_iseq.simple_params:
        raise UnsupportedOperation(
            "method '%s' has parameters RPyYARV does not support"
            % symbols.name_of(w_method.mid))
    _check_argc(w_method.mid, len(args_w), callee_iseq.nparams)
    callee = Frame(callee_iseq, w_recv)
    i = 0
    while i < len(args_w):
        callee.locals[i] = args_w[i]
        i += 1
    return execute(callee_iseq, callee)


def _check_argc(mid, argc, want):
    if argc != want:
        raise UnsupportedOperation(
            "wrong number of arguments to '%s' (given %d, expected %d)"
            % (symbols.name_of(mid), argc, want))


@unroll_safe
def _drop(frame, sp):
    while frame.sp > sp:
        frame.pop()


def _to_s(w_x):
    if isinstance(w_x, W_String):
        return w_x
    return W_String(w_x.to_s_str())


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'],
                      get_printable_location=get_printable_location)


def execute(iseq, frame):
    pc = 0
    while True:
        jitdriver.jit_merge_point(iseq=iseq, pc=pc, frame=frame)
        # rebound from the green iseq each iteration; hoisting it would leave a
        # live variable across the merge point that is neither green nor red
        code = iseq.code
        opcode = code[pc]
        if debug.state.enabled:
            debug.trace_insn(iseq, pc, frame)
        pc += 1

        if opcode == insns.NOP:
            pass
        elif opcode == insns.PUTNIL:
            frame.push(w_nil)
        elif opcode == insns.PUTSELF:
            frame.push(frame.w_self)
        elif opcode == insns.PUTOBJECT:
            idx = code[pc]
            pc += 1
            frame.push(iseq.consts[idx])
        elif opcode == insns.GETLOCAL:
            idx = code[pc]
            pc += 1
            assert idx >= 0
            frame.push(frame.locals[idx])
        elif opcode == insns.SETLOCAL:
            idx = code[pc]
            pc += 1
            assert idx >= 0
            frame.locals[idx] = frame.pop()
        elif opcode == insns.DUP:
            w_x = frame.pop()
            frame.push(w_x)
            frame.push(w_x)
        elif opcode == insns.POP:
            frame.pop()
        elif opcode == insns.SWAP:
            w_a = frame.pop()
            w_b = frame.pop()
            frame.push(w_a)
            frame.push(w_b)
        elif opcode == insns.EXPANDARRAY:
            n = code[pc]
            pc += 1
            w_ary = frame.pop()
            if not isinstance(w_ary, W_Array):
                raise UnsupportedOperation('expandarray needs an Array, got %s'
                                           % w_ary.repr())
            items_w = w_ary.items_w
            i = n - 1
            while i >= 0:
                if i < len(items_w):
                    frame.push(items_w[i])
                else:
                    frame.push(w_nil)
                i -= 1
        elif opcode == insns.OPT_PLUS:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_add(w_a, w_b))
        elif opcode == insns.OPT_MINUS:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_sub(w_a, w_b))
        elif opcode == insns.OPT_MULT:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_mul(w_a, w_b))
        elif opcode == insns.OPT_LT:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_lt(w_a, w_b))
        elif opcode == insns.OPT_GT:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_gt(w_a, w_b))
        elif opcode == insns.OPT_LE:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_le(w_a, w_b))
        elif opcode == insns.OPT_GE:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_ge(w_a, w_b))
        elif opcode == insns.OPT_EQ:
            w_b = frame.pop()
            w_a = frame.pop()
            frame.push(helpers.w_eq(w_a, w_b))
        elif opcode == insns.OBJTOSTRING:
            frame.push(_to_s(frame.pop()))
        elif opcode == insns.ANYTOSTRING:
            w_str = frame.pop()
            w_val = frame.pop()
            if not isinstance(w_str, W_String):
                raise UnsupportedOperation('to_s on %s did not return a String'
                                           % w_val.repr())
            frame.push(w_str)
        elif opcode == insns.CONCATSTRINGS:
            n = code[pc]
            pc += 1
            parts = [''] * n
            i = n - 1
            while i >= 0:
                parts[i] = frame.pop().str_w()
                i -= 1
            frame.push(W_String(''.join(parts)))
        elif opcode == insns.DEFINEMETHOD:
            mid = code[pc]
            w_body = iseq.consts[code[pc + 1]]
            pc += 2
            w_self = frame.w_self
            w_self.define_method(mid, W_ISeqMethod(
                mid, _as_iseq(w_body), w_self.defines_private()))
        elif opcode == insns.OPT_SEND_WITHOUT_BLOCK:
            idx = code[pc]
            pc += 1
            frame.push(invoke(frame, _callinfo(iseq, idx)))
        elif opcode == insns.SEND:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            w_ci = _callinfo(iseq, idx)
            if block != NO_BLOCK_ISEQ:
                raise UnsupportedOperation(
                    "send with a block is not supported: '%s'"
                    % symbols.name_of(w_ci.mid))
            frame.push(invoke(frame, w_ci))
        elif opcode == insns.JUMP:
            target = code[pc]
            pc += 1
            backward = target < pc
            pc = target
            if target < pc:
                jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHIF:
            target = code[pc]
            pc += 1
            if frame.pop().is_true():
                backward = target < pc
                pc = target
                if backward:
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHUNLESS:
            target = code[pc]
            pc += 1
            if not frame.pop().is_true():
                backward = target < pc
                pc = target
                if backward:
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.LEAVE:
            return frame.pop()
        else:
            raise UnsupportedOperation('unknown opcode %d' % opcode)


def run(iseq):
    debug.dump_iseq(iseq)
    w_ret = execute(iseq, Frame(iseq))
    debug.summary()
    return w_ret
