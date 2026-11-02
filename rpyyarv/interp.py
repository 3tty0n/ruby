from rpyyarv import classlib
from rpyyarv import debug
from rpyyarv import insns
from rpyyarv import helpers
from rpyyarv import optable
from rpyyarv import symbols
from rpyyarv.error import UnsupportedOperation
from rpyyarv.frame import Cref, Frame
from rpyyarv.helpers import is_number
from rpyyarv.iseq import (W_Block, W_CallInfo, W_ConstPath, W_ISeq,
                          NO_BLOCK_ISEQ, tail_position)
from rpyyarv.methods import W_CFunc, W_ISeqMethod
from rpyyarv.objects import array as arraylib
from rpyyarv.objects.array import W_Array
from rpyyarv.objects.string import W_String
from rpyyarv.objects.klass import W_Class, w_object_class
from rpyyarv.objects.transparent import W_Integer, newbool, newint, w_nil
from rpyyarv.rlib import JitDriver, elidable, promote, unroll_safe


def _as_iseq(w_x):
    assert isinstance(w_x, W_ISeq)      # RPython downcast
    return w_x


def _callinfo(iseq, idx):
    w_ci = iseq.consts[idx]
    assert isinstance(w_ci, W_CallInfo)
    return w_ci


def _literal_block(iseq, frame, idx):
    if idx == NO_BLOCK_ISEQ:
        return None
    return W_Block(_as_iseq(iseq.consts[idx]), frame.w_self, frame)


@unroll_safe
def invoke(frame, iseq, w_ci, w_block, tail=False):
    # None is a restart signal only when the caller passes tail=True.
    argc = w_ci.argc
    recv_at = frame.sp - argc - 1
    if recv_at < iseq.nlocals:
        raise UnsupportedOperation(
            "call to '%s' with %d argument(s) underflows the stack"
            % (symbols.name_of(w_ci.mid), argc))
    if not w_ci.simple:
        raise UnsupportedOperation(
            "call to '%s' passes arguments RPyYARV does not support"
            % symbols.name_of(w_ci.mid))

    w_recv = frame.peek(recv_at)
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
        if (tail and callee_iseq is iseq and w_block is None
                and frame.w_block is None and w_method.cref is frame.cref
                and not debug.is_enabled()):
            # The separate argument stack makes f(b, a) safe to copy in place.
            i = 0
            while i < argc:
                frame.setlocal(i, frame.peek(recv_at + 1 + i))
                i += 1
            while i < callee_iseq.nlocals:
                frame.setlocal(i, w_nil)
                i += 1
            _drop(frame, iseq.nlocals)
            frame.w_self = w_recv
            return None
        callee = Frame(callee_iseq, w_recv, None, w_block, w_method.cref,
                       w_method)
        i = 0
        while i < argc:
            callee.setlocal(i, frame.peek(recv_at + 1 + i))
            i += 1
        _drop(frame, recv_at)
        if not debug.is_enabled():
            return execute(callee_iseq, callee)
        traced_w = []
        i = 0
        while i < argc:
            traced_w.append(callee.getlocal(i))
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
        args_w.append(frame.peek(recv_at + 1 + i))
        i += 1
    _drop(frame, recv_at)
    if not debug.is_enabled():
        return w_method.call(w_recv, args_w, w_block)
    debug.trace_enter(w_ci.mid, args_w)
    w_ret = w_method.call(w_recv, args_w, w_block)
    debug.trace_leave(w_ci.mid, w_ret)
    return w_ret


def call_method(w_method, w_recv, args_w, w_block):
    if isinstance(w_method, W_CFunc):
        if w_method.arity >= 0:
            _check_argc(w_method.mid, len(args_w), w_method.arity)
        return w_method.call(w_recv, args_w, w_block)

    assert isinstance(w_method, W_ISeqMethod)
    callee_iseq = w_method.w_iseq
    if not callee_iseq.simple_params:
        raise UnsupportedOperation(
            "method '%s' has parameters RPyYARV does not support"
            % symbols.name_of(w_method.mid))
    _check_argc(w_method.mid, len(args_w), callee_iseq.nparams)
    callee = Frame(callee_iseq, w_recv, None, w_block, w_method.cref,
                   w_method)
    i = 0
    while i < len(args_w):
        callee.setlocal(i, args_w[i])
        i += 1
    return execute(callee_iseq, callee)


@unroll_safe
def call_block(w_block, args_w):
    w_iseq = w_block.w_iseq
    if not w_iseq.simple_params:
        raise UnsupportedOperation(
            "block '%s' has parameters RPyYARV does not support" % w_iseq.name)
    if (w_iseq.nparams > 1 and len(args_w) == 1
            and isinstance(args_w[0], W_Array)):
        raise UnsupportedOperation(
            "block '%s' would splat its Array argument, which RPyYARV does "
            "not support yet" % w_iseq.name)
    callee = Frame(w_iseq, w_block.w_self, w_block.outer, None,
                   w_block.outer.cref)
    i = 0
    while i < len(args_w) and i < w_iseq.nparams:
        callee.setlocal(i, args_w[i])
        i += 1
    return execute(w_iseq, callee)


@unroll_safe
def _method_frame(frame):
    while frame.outer is not None:
        frame = frame.outer
    return frame


@unroll_safe
def yield_block(frame, w_ci):
    if not w_ci.simple:
        raise UnsupportedOperation(
            "yield passes arguments RPyYARV does not support")
    w_block = _method_frame(frame).w_block
    if w_block is None:
        raise UnsupportedOperation('no block given (yield)')
    argc = w_ci.argc
    args_w = [w_nil] * argc
    i = argc - 1
    while i >= 0:
        args_w[i] = frame.pop()
        i -= 1
    return call_block(w_block, args_w)


@unroll_safe
def invoke_super(frame, w_ci, w_block):
    if not w_ci.simple:
        raise UnsupportedOperation(
            "super passes arguments RPyYARV does not support")
    method_frame = _method_frame(frame)
    w_method = method_frame.w_method
    if w_method is None or w_method.w_owner is None:
        raise UnsupportedOperation('super called outside of method')
    if w_block is None:
        w_block = method_frame.w_block
    args_w = [w_nil] * w_ci.argc
    i = w_ci.argc - 1
    while i >= 0:
        args_w[i] = frame.pop()
        i -= 1
    w_recv = frame.pop()
    w_target = None
    w_super = w_method.w_owner.w_superclass
    if w_super is not None:
        w_target = w_super.find_method(w_method.mid)
    if w_target is None:
        raise UnsupportedOperation("super: no superclass method '%s' for %s"
                                   % (symbols.name_of(w_method.mid),
                                      w_recv.repr()))
    return call_method(w_target, w_recv, args_w, w_block)


def _check_argc(mid, argc, want):
    if argc != want:
        raise UnsupportedOperation(
            "wrong number of arguments to '%s' (given %d, expected %d)"
            % (symbols.name_of(mid), argc, want))


@unroll_safe
def _drop(frame, sp):
    while frame.sp > sp:
        frame.pop()


TO_S = symbols.intern('to_s')
AREF = symbols.intern('[]')
LENGTH = symbols.intern('length')
EQ = symbols.intern('==')
NEQ = symbols.intern('!=')
NOT = symbols.intern('!')
DIV = symbols.intern('/')
PLUS = symbols.intern('+')
MINUS = symbols.intern('-')
MULT = symbols.intern('*')
LT = symbols.intern('<')
GT = symbols.intern('>')
LE = symbols.intern('<=')
GE = symbols.intern('>=')
NEW = symbols.intern('new')
# vm_method.c makes these private wherever they are defined
ALWAYS_PRIVATE = [symbols.intern(name) for name in [
    'initialize', 'initialize_copy', 'initialize_clone', 'initialize_dup',
    'respond_to_missing?']]
MOD = symbols.intern('%')
SIZE = symbols.intern('size')
ASET = symbols.intern('[]=')


def send(w_recv, mid, args_w):
    return call_method(w_recv.lookup_method(mid), w_recv, args_w, None)


def send_op(w_recv, mid, args_w):
    w_method = w_recv.lookup_method(mid)
    if w_method.private:
        raise UnsupportedOperation("private method '%s' called for %s"
                                   % (symbols.name_of(mid), w_recv.repr()))
    return call_method(w_method, w_recv, args_w, None)


def _uninitialized_constant(w_scope, mid):
    name = symbols.name_of(mid)
    if w_scope is not w_object_class:
        name = w_scope.name + '::' + name
    return UnsupportedOperation('uninitialized constant %s' % name)


@unroll_safe
def _lexical_const(cref, mid):
    scope = cref
    while scope is not None:
        w_value = scope.w_class.find_const(mid)
        if w_value is not None:
            return w_value
        scope = scope.parent
    w_class = _const_base(cref)
    w_value = w_class.find_const_in_ancestors(mid, False)
    if w_value is None:
        raise _uninitialized_constant(w_class, mid)
    return w_value


@unroll_safe
def _const(cref, w_path):
    i = 0
    if w_path.absolute:
        w_scope = w_object_class
    else:
        w_scope = _lexical_const(cref, w_path.mids[0])
        i = 1
    while i < len(w_path.mids):
        mid = w_path.mids[i]
        if not isinstance(w_scope, W_Class):
            raise UnsupportedOperation('%s is not a class/module'
                                       % w_scope.repr())
        w_value = w_scope.find_const_in_ancestors(
            mid, w_scope is not w_object_class)
        if w_value is None:
            raise _uninitialized_constant(w_scope, mid)
        w_scope = w_value
        i += 1
    return w_scope


def _const_base(cref):
    if cref is None:
        return w_object_class
    return cref.w_class


def _define_class(w_cbase, mid, w_super, flags):
    if flags & optable.DEFINECLASS_FLAG_HAS_SUPERCLASS:
        if not isinstance(w_super, W_Class):
            raise UnsupportedOperation(
                'superclass must be an instance of Class (given an instance '
                'of %s)' % w_super.getclass().name)
    else:
        w_super = None
    if not isinstance(w_cbase, W_Class):
        raise UnsupportedOperation('%s is not a class/module'
                                   % w_cbase.repr())
    w_class = w_cbase.find_const(mid)
    if w_class is not None:
        if not isinstance(w_class, W_Class):
            raise UnsupportedOperation('%s is not a class'
                                       % symbols.name_of(mid))
        if w_super is not None and w_class.w_superclass is not w_super:
            raise UnsupportedOperation('superclass mismatch for class %s'
                                       % symbols.name_of(mid))
        if w_class.builtin:
            raise UnsupportedOperation(
                'reopening the built-in class %s is not supported yet'
                % w_class.name)
        return w_class
    if w_super is None:
        w_super = w_object_class
    if w_super.builtin and w_super is not w_object_class:
        raise UnsupportedOperation(
            'subclassing the built-in class %s is not supported yet'
            % w_super.name)
    name = symbols.name_of(mid)
    if w_cbase is not w_object_class:
        name = w_cbase.name + '::' + name
    w_class = W_Class(name, w_super)
    w_cbase.set_const(mid, w_class)
    return w_class


def _to_s(w_x):
    if isinstance(w_x, W_String):
        return w_x
    return call_method(w_x.lookup_method(TO_S), w_x, [], None)


def to_s_string(w_x):
    """w_x.to_s as a String, as Kernel#puts takes it."""
    w_str = _to_s(w_x)
    if not isinstance(w_str, W_String):
        raise UnsupportedOperation('to_s on %s did not return a String'
                                   % w_x.repr())
    return w_str


@elidable
def _call_tail(iseq, w_ci, pc):
    # Hand-built ISeqs have no precomputed flag.
    if w_ci.tail is not None:
        return w_ci.tail
    return tail_position(iseq.code, pc)


@elidable
def _call_tail(iseq, w_ci, pc):
    # Hand-built ISeqs have no precomputed flag.
    if w_ci.tail is not None:
        return w_ci.tail
    return tail_position(iseq.code, pc)


def get_printable_location(pc, iseq):
    return '%s@%d %s' % (iseq.name, pc, insns.NAMES[iseq.code[pc]])


jitdriver = JitDriver(greens=['pc', 'iseq'], reds=['frame'],
                      virtualizables=['frame'], is_recursive=True,
                      get_printable_location=get_printable_location)


def execute(iseq, frame):
    pc = 0
    while True:
        jitdriver.jit_merge_point(iseq=iseq, pc=pc, frame=frame)
        # rebound from the green iseq each iteration; hoisting it would leave a
        # live variable across the merge point that is neither green nor red
        code = iseq.code
        opcode = code[pc]
        if debug.is_enabled():
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
        elif opcode == insns.PUTCHILLEDSTRING:
            idx = code[pc]
            pc += 1
            frame.push(W_String(iseq.consts[idx].str_w())) 
        elif opcode == insns.GETLOCAL:
            idx = code[pc]
            level = code[pc + 1]
            pc += 2
            assert idx >= 0
            if level == 0:
                frame.push(frame.getlocal(idx))
            else:
                frame.push(frame.outer_at(level).getlocal(idx))
        elif opcode == insns.SETLOCAL:
            idx = code[pc]
            level = code[pc + 1]
            pc += 2
            assert idx >= 0
            if level == 0:
                frame.setlocal(idx, frame.pop())
            else:
                frame.outer_at(level).setlocal(idx, frame.pop())
        elif opcode == insns.GETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            frame.push(frame.w_self.get_ivar(mid))
        elif opcode == insns.SETINSTANCEVARIABLE:
            mid = code[pc]
            pc += 1
            frame.w_self.set_ivar(mid, frame.pop())
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
        elif opcode == insns.TOPN:
            n = code[pc]
            pc += 1
            frame.push(frame.topn(n))
        elif opcode == insns.SETN:
            n = code[pc]
            pc += 1
            frame.set_topn(n, frame.topn(0))
        elif opcode == insns.DUPN:
            n = code[pc]
            pc += 1
            i = 0
            while i < n:
                frame.push(frame.topn(n - 1))
                i += 1
        elif opcode == insns.ADJUSTSTACK:
            n = code[pc]
            pc += 1
            _drop(frame, frame.sp - n)
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
            if (is_number(w_a) and is_number(w_b)) or (
                    isinstance(w_a, W_String) and isinstance(w_b, W_String)):
                frame.push(helpers.w_add(w_a, w_b))
            else:
                frame.push(send_op(w_a, PLUS, [w_b]))
        elif opcode == insns.OPT_MINUS:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_sub(w_a, w_b))
            else:
                frame.push(send_op(w_a, MINUS, [w_b]))
        elif opcode == insns.OPT_MULT:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_mul(w_a, w_b))
            else:
                frame.push(send_op(w_a, MULT, [w_b]))
        elif opcode == insns.OPT_DIV:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_div(w_a, w_b))
            else:
                frame.push(send_op(w_a, DIV, [w_b]))
        elif opcode == insns.OPT_MOD:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_mod(w_a, w_b))
            else:
                frame.push(send_op(w_a, MOD, [w_b]))
        elif opcode == insns.OPT_LT:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_lt(w_a, w_b))
            else:
                frame.push(send_op(w_a, LT, [w_b]))
        elif opcode == insns.OPT_GT:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_gt(w_a, w_b))
            else:
                frame.push(send_op(w_a, GT, [w_b]))
        elif opcode == insns.OPT_LE:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_le(w_a, w_b))
            else:
                frame.push(send_op(w_a, LE, [w_b]))
        elif opcode == insns.OPT_GE:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_ge(w_a, w_b))
            else:
                frame.push(send_op(w_a, GE, [w_b]))
        elif opcode == insns.OPT_EQ:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(helpers.w_eq(w_a, w_b))
            else:
                frame.push(send_op(w_a, EQ, [w_b]))
        elif opcode == insns.OPT_NEQ:
            w_b = frame.pop()
            w_a = frame.pop()
            if is_number(w_a) and is_number(w_b):
                frame.push(newbool(not helpers.w_eq(w_a, w_b).is_true()))
            else:
                frame.push(send_op(w_a, NEQ, [w_b]))
        elif opcode == insns.OPT_NOT:
            frame.push(send_op(frame.pop(), NOT, []))
        elif opcode == insns.OPT_AREF:
            w_key = frame.pop()
            w_recv = frame.pop()
            if isinstance(w_recv, W_Array) and isinstance(w_key, W_Integer):
                frame.push(arraylib.aref(w_recv, w_key.int_w()))
            else:
                frame.push(send_op(w_recv, AREF, [w_key]))
        elif opcode == insns.OPT_ASET:
            w_value = frame.pop()
            w_key = frame.pop()
            w_recv = frame.pop()
            if isinstance(w_recv, W_Array) and isinstance(w_key, W_Integer):
                frame.push(arraylib.aset(w_recv, w_key.int_w(), w_value))
            else:
                frame.push(send_op(w_recv, ASET, [w_key, w_value]))
        elif opcode == insns.OPT_LENGTH or opcode == insns.OPT_SIZE:
            w_recv = frame.pop()
            if isinstance(w_recv, W_Array):
                frame.push(newint(len(w_recv.items_w)))
            elif opcode == insns.OPT_LENGTH:
                frame.push(send_op(w_recv, LENGTH, []))
            else:
                frame.push(send_op(w_recv, SIZE, []))
        elif opcode == insns.OBJTOSTRING:
            frame.push(_to_s(frame.pop()))
        elif opcode == insns.ANYTOSTRING:
            w_str = frame.pop()
            w_val = frame.pop()
            if not isinstance(w_str, W_String):
                raise UnsupportedOperation('to_s on %s did not return a String'
                                           % w_val.repr())
            frame.push(w_str)
        elif opcode == insns.NEWARRAY:
            n = code[pc]
            pc += 1
            items_w = [w_nil] * n
            i = n - 1
            while i >= 0:
                items_w[i] = frame.pop()
                i -= 1
            frame.push(W_Array(items_w))
        elif opcode == insns.DUPARRAY:
            idx = code[pc]
            pc += 1
            w_ary = iseq.consts[idx]
            assert isinstance(w_ary, W_Array)
            frame.push(W_Array(w_ary.items_w[:]))
        elif opcode == insns.CONCATSTRINGS:
            n = code[pc]
            pc += 1
            parts = [''] * n
            i = n - 1
            while i >= 0:
                parts[i] = frame.pop().str_w()
                i -= 1
            frame.push(W_String(''.join(parts)))
        elif opcode == insns.PUTSPECIALOBJECT:
            frame.push(_const_base(frame.cref))
        elif opcode == insns.DEFINECLASS:
            mid = code[pc]
            w_body = _as_iseq(iseq.consts[code[pc + 1]])
            flags = code[pc + 2]
            pc += 3
            w_super = frame.pop()
            w_class = _define_class(frame.pop(), mid, w_super, flags)
            frame.push(execute(w_body, Frame(w_body, w_class, None, None,
                                             Cref(w_class, frame.cref))))
        elif opcode == insns.DEFINEMETHOD:
            mid = code[pc]
            w_body = iseq.consts[code[pc + 1]]
            pc += 2
            w_self = frame.w_self
            private = w_self.defines_private() or mid in ALWAYS_PRIVATE
            w_owner = w_self.method_owner()
            w_owner.add_method(mid, W_ISeqMethod(
                mid, _as_iseq(w_body), private, frame.cref, w_owner))
        elif opcode == insns.DEFINESMETHOD:
            mid = code[pc]
            w_body = iseq.consts[code[pc + 1]]
            pc += 2
            w_obj = frame.pop()
            if not isinstance(w_obj, W_Class):
                raise UnsupportedOperation(
                    'a singleton method on %s is not supported yet'
                    % w_obj.repr())
            w_owner = w_obj.singleton_class()
            w_owner.add_method(mid, W_ISeqMethod(
                mid, _as_iseq(w_body), False, frame.cref, w_owner))
        elif opcode == insns.OPT_SEND_WITHOUT_BLOCK:
            idx = code[pc]
            pc += 1
            w_ci = _callinfo(iseq, idx)
            w_ret = invoke(frame, iseq, w_ci, None,
                           _call_tail(iseq, w_ci, pc))
            if w_ret is None:
                pc = 0
                jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
            else:
                frame.push(w_ret)
        elif opcode == insns.SEND:
            idx = code[pc]
            w_block = _literal_block(iseq, frame, code[pc + 1])
            pc += 2
            w_ci = _callinfo(iseq, idx)
            w_ret = invoke(frame, iseq, w_ci, w_block,
                           _call_tail(iseq, w_ci, pc))
            if w_ret is None:
                pc = 0
                jitdriver.can_enter_jit(iseq=iseq, pc=pc, frame=frame)
            else:
                frame.push(w_ret)
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
        elif opcode == insns.INVOKESUPER:
            w_ci = _callinfo(iseq, code[pc])
            w_block = _literal_block(iseq, frame, code[pc + 1])
            pc += 2
            frame.push(invoke_super(frame, w_ci, w_block))
        elif opcode == insns.INVOKEBLOCK:
            w_ci = _callinfo(iseq, code[pc])
            pc += 1
            frame.push(yield_block(frame, w_ci))
        elif opcode == insns.OPT_NEW:
            w_ci = _callinfo(iseq, code[pc])
            target = code[pc + 1]
            pc += 2
            # Below the arguments: the class, then a nil slot for the result
            w_class = frame.topn(w_ci.argc)
            if (isinstance(w_class, W_Class) and isinstance(
                    w_class.lookup_method(NEW), classlib.W_New)):
                w_obj = classlib.allocate(w_class)
                frame.set_topn(w_ci.argc, w_obj)
                frame.set_topn(w_ci.argc + 1, w_obj)
            else:
                pc = target
        elif opcode == insns.OPT_GETCONSTANT_PATH:
            w_path = iseq.consts[code[pc]]
            pc += 1
            assert isinstance(w_path, W_ConstPath)
            frame.push(_const(promote(frame.cref), w_path))
        elif opcode == insns.SETCONSTANT:
            mid = code[pc]
            pc += 1
            w_cbase = frame.pop()
            w_value = frame.pop()
            if not isinstance(w_cbase, W_Class):
                raise UnsupportedOperation('%s is not a class/module'
                                           % w_cbase.repr())
            w_cbase.set_const(mid, w_value)
        elif opcode == insns.LEAVE:
            return frame.pop()
        else:
            raise UnsupportedOperation('unknown opcode %d' % opcode)


def run(iseq):
    debug.dump_iseq(iseq)
    w_ret = execute(iseq, Frame(iseq))
    debug.summary()
    return w_ret
