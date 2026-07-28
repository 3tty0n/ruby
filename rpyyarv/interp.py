import insns
import helpers
from error import UnsupportedOperation
from frame import Frame
from objects.transparent import w_nil

# Annotation-zero baseline: no rpython imports, no JIT hints. This is the
# measurement reference for later annotated versions.


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
