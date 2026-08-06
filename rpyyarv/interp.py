import boot
import debug
import dispatch
import gcroots
import helpers
import insns
import optable
import rubycall
import symbols
import value
from error import UnsupportedOperation
from frame import Frame
from iseq import NO_BLOCK_ISEQ
from rlib import JitDriver, unroll_safe, dont_look_inside, promote

TO_S = symbols.intern('to_s')
DUP = symbols.intern('dup')


def define_method(frame, mid, w_iseq):
    """A def in a class body lands on that class; a toplevel def lands on
    Object as a private method, which is where Ruby puts it too."""
    klass = frame.cref
    if klass == 0:
        dispatch.define(value.core_class(value.C_OBJECT), mid, w_iseq, True)
    else:
        dispatch.define(klass, mid, w_iseq, False)


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
    # Promoted, so a trace guards the class word once and the lookup below
    # folds away: that guard is the inline cache.
    klass = promote(value.class_of(recv))
    entry = dispatch.lookup(klass, w_ci.mid)
    callee_iseq = None
    if entry is not None and (w_ci.fcall or not entry.private):
        callee_iseq = entry.w_iseq

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


def _const_base(frame):
    """The cref's constant base: the class a class body is defining into, and
    Object everywhere else. TODO: a nested cref chain, once modules land."""
    if frame.cref != 0:
        return frame.cref
    return value.core_class(value.C_OBJECT)


def _defineclass(mid, w_body, cbase, super_v):
    klass = dispatch.define_class(cbase, mid, super_v)
    return execute(w_body, Frame(w_body, klass, klass))


@dont_look_inside
def _opt_new_alloc(klass):
    """insns.def's fast half, minus the stack writes: a fresh instance, or 0
    for the miss branch. Only classes RPyYARV made can take it -- nothing
    else is known to have kept Class#new, and their `initialize` is in
    RPyYARV's registry rather than CRuby's."""
    if not dispatch.is_known_class(klass):
        return 0
    return dispatch.alloc(klass)


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
        elif opcode == insns.OPT_DIV:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.div(a, b))
        elif opcode == insns.OPT_MOD:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.mod(a, b))
        elif opcode == insns.OPT_NEQ:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.neq(a, b))
        elif opcode == insns.GETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            frame.push(dispatch.ivar_get(frame.self_val, mid))
        elif opcode == insns.SETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            dispatch.ivar_set(frame.self_val, mid, frame.pop())
        elif opcode == insns.PUTSPECIALOBJECT:
            # The loader has already refused every kind but CONST_BASE.
            pc += 1
            frame.push(_const_base(frame))
        elif opcode == insns.OPT_GETCONSTANT_PATH:
            mid = code[pc]
            pc += 1
            frame.push(dispatch.const_get(_const_base(frame), mid))
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
            frame.push(_defineclass(mid, w_body, cbase, super_v))
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
                # The class becomes the receiver of the `initialize` send that
                # follows, and the slot below it becomes that send's result.
                frame.stack[at] = obj
                frame.stack[below] = obj
        elif opcode == insns.DEFINEMETHOD:
            mid = code[pc]
            w_body = iseq.iseqs[code[pc + 1]]
            pc += 2
            define_method(frame, mid, w_body)
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
