import boot
import debug
import gcroots
import helpers
import insns
import rubycall
import symbols
import value
from error import UnsupportedOperation
from frame import Frame
from iseq import NO_BLOCK_ISEQ
from rlib import JitDriver, unroll_safe, dont_look_inside

TO_S = symbols.intern('to_s')
DUP = symbols.intern('dup')


class _Methods(object):
    # Phase 1 dispatch: one global table filled by definemethod. Phase 2
    # replaces it with a real class/inline-cache design.
    def __init__(self):
        self.table = {}


methods = _Methods()


def define_method(mid, w_iseq):
    methods.table[mid] = w_iseq


def lookup(mid):
    return methods.table.get(mid, None)


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

    rubycall.gc_stress_point()
    recv = frame.stack[recv_at]
    callee_iseq = lookup(w_ci.mid)

    if callee_iseq is not None:
        if not callee_iseq.simple_params:
            raise UnsupportedOperation(
                "method '%s' has parameters RPyYARV does not support"
                % symbols.name_of(w_ci.mid))
        if argc != callee_iseq.nparams:
            raise UnsupportedOperation(
                "wrong number of arguments to '%s' (given %d, expected %d)"
                % (symbols.name_of(w_ci.mid), argc, callee_iseq.nparams))
        callee = Frame(callee_iseq, recv)
        i = 0
        while i < argc:
            callee.locals[i] = frame.stack[recv_at + 1 + i]
            i += 1
        _drop(frame, recv_at)
        if not debug.state.enabled:
            return execute(callee_iseq, callee)
        args = []
        i = 0
        while i < argc:
            args.append(callee.locals[i])
            i += 1
        debug.trace_enter(w_ci.mid, args)
        ret = execute(callee_iseq, callee)
        debug.trace_leave(w_ci.mid, ret)
        return ret

    # Everything RPyYARV has not taken over goes back to CRuby, which is how
    # puts and every other builtin keeps working.
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    if not debug.state.enabled:
        return rubycall.call(recv, w_ci.mid, args)
    debug.trace_enter(w_ci.mid, args)
    ret = rubycall.call(recv, w_ci.mid, args)
    debug.trace_leave(w_ci.mid, ret)
    return ret


@unroll_safe
def _drop(frame, sp):
    while frame.sp > sp:
        frame.pop()


@dont_look_inside
def _to_s(v):
    if rubycall.is_string(v):
        return v
    return rubycall.call0(v, TO_S)


@dont_look_inside
def _concat(parts):
    return boot.str_concat(parts)


@dont_look_inside
def _expand(frame, v, n):
    if value.is_immediate(v) or not boot.is_array(v):
        raise UnsupportedOperation('expandarray needs an Array, got %s'
                                   % value.repr_of(v))
    size = boot.ary_len(v)
    i = n - 1
    while i >= 0:
        if i < size:
            frame.push(boot.ary_entry(v, i))
        else:
            frame.push(value.Q_NIL)
        i -= 1


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'],
                      get_printable_location=get_printable_location)


def execute(iseq, frame):
    gcroots.push_frame(frame)
    try:
        return _execute(iseq, frame)
    finally:
        gcroots.pop_frame(frame)


def _execute(iseq, frame):
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
            pc += 1
            _expand(frame, frame.pop(), n)
        elif opcode == insns.OPT_PLUS:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.add(a, b))
        elif opcode == insns.OPT_MINUS:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.sub(a, b))
        elif opcode == insns.OPT_MULT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.mul(a, b))
        elif opcode == insns.OPT_LT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.lt(a, b))
        elif opcode == insns.OPT_GT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.gt(a, b))
        elif opcode == insns.OPT_LE:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.le(a, b))
        elif opcode == insns.OPT_GE:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.ge(a, b))
        elif opcode == insns.OPT_EQ:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.eq(a, b))
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
        elif opcode == insns.DEFINEMETHOD:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            pc += 2
            define_method(mid, w_body)
        elif opcode == insns.OPT_SEND_WITHOUT_BLOCK:
            idx = code[pc]
            pc += 1
            frame.push(invoke(frame, iseq.callinfos[idx]))
        elif opcode == insns.SEND:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            w_ci = iseq.callinfos[idx]
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
            if backward:
                jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHIF:
            target = code[pc]
            pc += 1
            if value.is_true(frame.pop()):
                backward = target < pc
                pc = target
                if backward:
                    jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
        elif opcode == insns.BRANCHUNLESS:
            target = code[pc]
            pc += 1
            if not value.is_true(frame.pop()):
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
    ret = execute(iseq, Frame(iseq, boot.top_self()))
    debug.summary()
    return ret
