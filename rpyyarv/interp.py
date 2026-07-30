import insns
import helpers
import symbols
from error import UnsupportedOperation
from frame import Frame
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from methods import W_Method
from objects.transparent import w_nil

# Annotation-zero baseline: no rpython imports, no JIT hints.


def _as_iseq(w_x):
    assert isinstance(w_x, W_ISeq)      # RPython downcast
    return w_x


def _callinfo(iseq, idx):
    w_ci = iseq.consts[idx]
    assert isinstance(w_ci, W_CallInfo)
    return w_ci


def invoke(frame, w_ci):
    """One call. The receiver sits below its arguments; both are popped."""
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
    callee_iseq = w_method.w_iseq
    if not callee_iseq.simple_params:
        raise UnsupportedOperation(
            "method '%s' has parameters RPyYARV does not support"
            % symbols.name_of(w_ci.mid))
    if argc != callee_iseq.nparams:
        raise UnsupportedOperation(
            "wrong number of arguments to '%s' (given %d, expected %d)"
            % (symbols.name_of(w_ci.mid), argc, callee_iseq.nparams))

    callee = Frame(callee_iseq, w_recv)
    i = 0
    while i < argc:
        callee.locals[i] = frame.stack[recv_at + 1 + i]
        i += 1
    while frame.sp > recv_at:
        frame.sp -= 1
        frame.stack[frame.sp] = None

    return execute(callee_iseq, callee)


def execute(iseq, frame):
    code = iseq.code
    pc = 0
    while True:
        opcode = code[pc]
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
            frame.push(frame.locals[idx])
        elif opcode == insns.SETLOCAL:
            idx = code[pc]
            pc += 1
            frame.locals[idx] = frame.pop()
        elif opcode == insns.DUP:
            w_x = frame.pop()
            frame.push(w_x)
            frame.push(w_x)
        elif opcode == insns.POP:
            frame.pop()
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
        elif opcode == insns.DEFINEMETHOD:
            mid = code[pc]
            w_body = iseq.consts[code[pc + 1]]
            pc += 2
            frame.w_self.define_method(mid, W_Method(mid, _as_iseq(w_body)))
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
            pc = code[pc]
        elif opcode == insns.BRANCHIF:
            target = code[pc]
            pc += 1
            if frame.pop().is_true():
                pc = target
        elif opcode == insns.BRANCHUNLESS:
            target = code[pc]
            pc += 1
            if not frame.pop().is_true():
                pc = target
        elif opcode == insns.LEAVE:
            return frame.pop()
        else:
            raise UnsupportedOperation('unknown opcode %d' % opcode)


def run(iseq):
    return execute(iseq, Frame(iseq))
