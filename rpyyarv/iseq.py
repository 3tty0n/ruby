"""Loaded code: W_ISeq.code is a flat list of ints.

Operands that are already ints (local
slots, branch targets, interned ids) sit in it directly; everything else --
literals, nested ISeqs, the W_CallInfo distilled from CALL_DATA -- goes into
consts and the code stream carries the index.
"""

from rpyyarv import insns
from rpyyarv import symbols
from rpyyarv.objects.base import W_Root
from rpyyarv.rlib import elidable

# A `send` whose call site has no block. Pool indices are >= 0.
NO_BLOCK_ISEQ = -1


@elidable
def tail_position(code, pc):
    # Forward-only, so the walk ends on cyclic bytecode.
    while pc < len(code):
        opcode = code[pc]
        if opcode == insns.LEAVE:
            return True
        if opcode == insns.NOP:
            pc += 1
        elif opcode == insns.JUMP and pc + 1 < len(code):
            target = code[pc + 1]
            if target <= pc:
                return False
            pc = target
        else:
            return False
    return False


class W_ISeq(W_Root):
    # The loader hands over finished lists; nothing appends afterwards, so the
    # JIT may fold code[pc] and consts[idx] away when pc and iseq are green.
    _immutable_fields_ = ['name', 'code[*]', 'consts[*]', 'nlocals',
                          'stack_max', 'nparams', 'simple_params']

    def __init__(self, name, code, consts, nlocals, stack_max,
                 nparams=0, simple_params=True):
        self.name = name
        self.code = code
        self.consts = consts
        self.nlocals = nlocals
        self.stack_max = stack_max
        # Required parameters, which YARV puts in locals[0:nparams] in order.
        self.nparams = nparams
        # False once the loader saw optional/rest/post/keyword/block
        # parameters; the call path refuses those rather than guessing.
        self.simple_params = simple_params

    def repr(self):
        return '<W_ISeq %s>' % self.name


class W_CallInfo(W_Root):
    _immutable_fields_ = ['mid', 'argc', 'simple', 'fcall', 'tail']

    def __init__(self, mid, argc, simple=True, fcall=True, tail=None):
        self.mid = mid
        self.argc = argc
        # False once the loader saw call flags outside SIMPLE_CALL_FLAGS.
        self.simple = simple
        # A receiverless call, or an explicit `self.`: may reach a private one.
        self.fcall = fcall
        # None for hand-built ISeqs.
        self.tail = tail

    def repr(self):
        return '<W_CallInfo %s argc=%d>' % (symbols.name_of(self.mid),
                                           self.argc)

class W_Block(W_Root):
    _immutable_fields_ = ['w_iseq', 'w_self', 'outer']

    def __init__(self, w_iseq, w_self, outer):
        self.w_iseq = w_iseq
        self.w_self = w_self
        self.outer = outer

    def repr(self):
        return '<W_Block %s>' % self.w_iseq.name


class W_ConstPath(W_Root):
    _immutable_fields_ = ['mids[*]']

    def __init__(self, mids):
        self.mids = mids

    def repr(self):
        return '<W_ConstPath %s>' % '::'.join(
            [symbols.name_of(mid) for mid in self.mids])
