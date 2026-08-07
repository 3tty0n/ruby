import block as block_mod
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
from error import RPyYarvError, UnsupportedOperation
from frame import Frame
from iseq import NO_BLOCK_ISEQ
from rlib import (JitDriver, always_inline, dont_look_inside, promote,
                  unroll_safe)

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
def invoke(frame, w_ci, w_block=None):
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
        if w_block is None:
            return _enter(frame, entry, recv, recv_at, argc, w_ci.mid, None)
        try:
            return _enter(frame, entry, recv, recv_at, argc, w_ci.mid,
                          w_block)
        except block_mod.BlockBreak, e:
            if e.w_block is not w_block:
                raise
            return e.value

    # Everything RPyYARV has not taken over goes back to CRuby, which is how
    # puts and every other builtin keeps working.
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    if w_block is not None:
        return _call_with_block(recv, w_ci.mid, args, w_block)
    if not debug.state.enabled:
        return rubycall.call(recv, w_ci.mid, args)
    debug.trace_enter(w_ci.mid, args)
    ret = rubycall.call(recv, w_ci.mid, args)
    debug.trace_leave(w_ci.mid, ret)
    return ret


@unroll_safe
def _enter(frame, entry, recv, recv_at, argc, mid, w_block=None):
    """Move argc arguments off the caller's stack into a fresh frame and run
    it. Shared by a plain send and by invokesuper."""
    callee_iseq = entry.w_iseq
    if not callee_iseq.simple_params:
        raise UnsupportedOperation(
            "method '%s' has parameters RPyYARV does not support"
            % symbols.name_of(mid))
    if argc != callee_iseq.nparams:
        raise UnsupportedOperation(
            "wrong number of arguments to '%s' (given %d, expected %d)"
            % (symbols.name_of(mid), argc, callee_iseq.nparams))
    callee = Frame(callee_iseq, recv, 0, entry)
    callee.block = w_block
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
    debug.trace_enter(mid, args)
    ret = execute(callee_iseq, callee)
    debug.trace_leave(mid, ret)
    return ret


@unroll_safe
def invoke_super(frame, w_ci):
    """super: the same lookup as a send, resumed above the class the running
    method was defined on."""
    entry = frame.entry
    if entry is None:
        raise UnsupportedOperation(
            'super outside a method body is not supported')
    argc = w_ci.argc
    recv_at = frame.sp - argc - 1
    if recv_at < 0:
        raise UnsupportedOperation(
            "super with %d argument(s) underflows the stack" % argc)
    if not w_ci.simple:
        raise UnsupportedOperation(
            "super in '%s' passes arguments RPyYARV does not support"
            % symbols.name_of(entry.mid))

    rubycall.gc_stress_point()
    target = dispatch.lookup_super(entry.owner, entry.mid)
    if target is None:
        # rb_call_super only works from inside a CRuby frame, and RPyYARV
        # never has one, so there is nothing to fall back to.
        raise UnsupportedOperation(
            "super from '%s' reaches a method RPyYARV did not define; "
            "calling CRuby's implementation of a superclass method is not "
            "supported" % symbols.name_of(entry.mid))
    return _enter(frame, target, frame.stack[recv_at], recv_at, argc,
                  entry.mid)


class _Blocks(object):
    """The reverse-direction reference of the GC design, as a stack.

    A block passed to a CRuby method is alive exactly for the extent of that
    rb_block_call, so pushing on the way in and popping on the way out is
    enough; C never sees anything but the index.
    """
    def __init__(self):
        self.stack = []
        self.error = None       # an RPython error the callback could not raise


blocks = _Blocks()


def block_callback(handle, argc, argv):
    """Called from C, inside rb_block_call. Must not let an RPython exception
    escape into libruby, so a failure is remembered and re-raised at the
    call site once rb_block_call has returned."""
    if blocks.error is not None:
        return boot.as_value(value.Q_NIL)
    w_block = blocks.stack[handle]
    args = boot.read_values(argv, argc)
    try:
        return boot.as_value(call_block(w_block, args))
    except block_mod.BlockBreak:
        # Unwinding a break would have to longjmp out of rb_block_call's
        # frames; that protocol is not implemented.
        blocks.error = UnsupportedOperation(
            'break out of a block passed to a CRuby method is not supported')
        return boot.as_value(value.Q_NIL)
    except RPyYarvError, e:
        blocks.error = e
        return boot.as_value(value.Q_NIL)


@dont_look_inside
def _call_with_block(recv, mid, args, w_block):
    blocks.stack.append(w_block)
    try:
        ret = rubycall.call_with_block(recv, mid, args,
                                       len(blocks.stack) - 1)
    finally:
        blocks.stack.pop()
    err = blocks.error
    if err is not None:
        blocks.error = None
        raise err
    return ret


@unroll_safe
def call_block(w_block, args):
    """Run a block's ISeq in a frame whose locals chain to the defining one."""
    b_iseq = w_block.w_iseq
    outer = w_block.frame
    callee = Frame(b_iseq, outer.self_val, outer.cref, outer.entry)
    callee.defining_frame = outer
    callee.block = w_block.outer
    callee.own_block = w_block
    n = len(args)
    if n > b_iseq.nparams:
        n = b_iseq.nparams
    i = 0
    while i < n:
        callee.locals[i] = args[i]
        i += 1
    try:
        return execute(b_iseq, callee)
    except block_mod.BlockNext, e:
        return e.value


@unroll_safe
def _outer_frame(frame, level):
    """The frame `level` steps up the block chain. Reading an outer frame's
    locals from a trace forces that frame's virtualizable; jit-summary's
    "virtualizables forced" is what that costs."""
    f = frame
    i = 0
    while i < level:
        f = f.defining_frame
        if f is None:
            raise UnsupportedOperation(
                'a local at level %d has no enclosing scope' % level)
        i += 1
    return f


@unroll_safe
def invoke_block(frame, w_ci):
    w_block = frame.block
    if w_block is None:
        raise UnsupportedOperation('yield without a block')
    argc = w_ci.argc
    at = frame.sp - argc
    if at < 0:
        raise UnsupportedOperation(
            'yield with %d argument(s) underflows the stack' % argc)
    args = [0] * argc
    i = 0
    while i < argc:
        args[i] = frame.stack[at + i]
        i += 1
    _drop(frame, at)
    return call_block(w_block, args)


# vm_core.h: throw_state's low bits are the RUBY_TAG_* value.
TAG_MASK = 0xf
TAG_BREAK = 2
TAG_NEXT = 3


def _throw(frame, throw_state, v):
    tag = throw_state & TAG_MASK
    if tag == TAG_NEXT:
        raise block_mod.BlockNext(v)
    if tag == TAG_BREAK:
        w_block = frame.own_block
        if w_block is None:
            raise UnsupportedOperation('break outside a block')
        raise block_mod.BlockBreak(w_block, v)
    raise UnsupportedOperation(
        'throw with tag %d (return/retry/redo) is not supported' % tag)


def install():
    boot.install_block_callback(block_callback)


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


@unroll_safe
def _newarray(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('newarray %d underflows the stack' % n)
    # Copied out but not popped: the frame keeps marking them until the shim
    # has them on the machine stack.
    values = [0] * n
    i = 0
    while i < n:
        values[i] = frame.stack[at + i]
        i += 1
    v = rubycall.ary_new(values)
    _drop(frame, at)
    return v


@unroll_safe
def _dupn(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('dupn %d underflows the stack' % n)
    i = 0
    while i < n:
        frame.push(frame.stack[at + i])
        i += 1


@unroll_safe
def _adjuststack(frame, n):
    if frame.sp - n < 0:
        raise UnsupportedOperation('adjuststack %d underflows the stack' % n)
    i = 0
    while i < n:
        frame.pop()
        i += 1


@unroll_safe
def _reverse(frame, n):
    at = frame.sp - n
    if at < 0:
        raise UnsupportedOperation('opt_reverse %d underflows the stack' % n)
    i = 0
    while i < n // 2:
        lo = at + i
        hi = frame.sp - 1 - i
        assert lo >= 0
        assert hi >= 0
        v = frame.stack[lo]
        frame.stack[lo] = frame.stack[hi]
        frame.stack[hi] = v
        i += 1


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
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            if packed == idx:
                frame.push(frame.locals[idx])
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                frame.push(_outer_frame(frame, level).locals[idx])
        elif opcode == insns.SETLOCAL:
            packed = code[pc]
            pc += 1
            idx = packed & optable.LOCAL_SLOT_MASK
            assert idx >= 0
            if packed == idx:
                frame.locals[idx] = frame.pop()
            else:
                level = packed >> optable.LOCAL_LEVEL_SHIFT
                _outer_frame(frame, level).locals[idx] = frame.pop()
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
            w_block = None
            if block != NO_BLOCK_ISEQ:
                w_block = block_mod.W_Block(iseq.iseqs[block], frame,
                                            frame.block)
            frame.push(invoke(frame, w_ci, w_block))
        elif opcode == insns.INVOKEBLOCK:
            idx = code[pc]
            pc += 1
            frame.push(invoke_block(frame, iseq.callinfos[idx]))
        elif opcode == insns.INVOKESUPER:
            idx = code[pc]
            block = code[pc + 1]
            pc += 2
            if block != NO_BLOCK_ISEQ:
                raise UnsupportedOperation(
                    'super with a block is not supported')
            frame.push(invoke_super(frame, iseq.callinfos[idx]))
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
        elif opcode == insns.OPT_AREF:
            idx = frame.pop()
            recv = frame.pop()
            frame.push(helpers.aref(recv, idx))
        elif opcode == insns.OPT_ASET:
            val = frame.pop()
            idx = frame.pop()
            recv = frame.pop()
            frame.push(helpers.aset(recv, idx, val))
        elif opcode == insns.OPT_LENGTH:
            frame.push(helpers.length(frame.pop()))
        elif opcode == insns.OPT_SIZE:
            frame.push(helpers.size(frame.pop()))
        elif opcode == insns.OPT_EMPTY_P:
            frame.push(helpers.empty_p(frame.pop()))
        elif opcode == insns.OPT_NOT:
            frame.push(helpers.opt_not(frame.pop()))
        elif opcode == insns.OPT_LTLT:
            b = frame.pop()
            a = frame.pop()
            frame.push(helpers.ltlt(a, b))
        else:
            raise UnsupportedOperation('unknown opcode %d' % opcode)


def run(iseq):
    debug.dump_iseq(iseq)
    ret = execute(iseq, Frame(iseq, boot.top_self()))
    debug.summary()
    return ret
