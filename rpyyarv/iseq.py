"""Loaded code: W_ISeq.code is a flat list of ints.

Operands that are already ints (local slots, branch targets, interned ids)
sit in it directly; everything else goes into a pool and the code stream
carries the index. The pools are split by type because `consts` holds raw
VALUEs, and an RPython list of ints cannot also hold objects.
"""

import symbols

# A `send` whose call site has no block. Pool indices are >= 0.
NO_BLOCK_ISEQ = -1

# The catch-table entry kinds RPyYARV interprets; see loader.py for the rest.
CATCH_RESCUE = 1
CATCH_ENSURE = 2


class W_Catch(object):
    """One catch-table entry; it covers a pc when start < epc <= end, epc
    being the pc *after* the raising instruction (vm.c:2911)."""
    _immutable_fields_ = ['kind', 'start', 'end', 'cont', 'sp', 'w_iseq']

    def __init__(self, kind, start, end, cont, sp, w_iseq):
        self.kind = kind
        self.start = start
        self.end = end
        self.cont = cont
        # The frame's sp when the catch ISeq's result lands.
        self.sp = sp
        self.w_iseq = w_iseq


class W_ISeq(object):
    # Nothing appends after the loader, so the JIT may fold code[pc] and
    # consts[idx] away when pc and iseq are green.
    _immutable_fields_ = ['name', 'code[*]', 'consts[*]', 'iseqs[*]',
                          'callinfos[*]', 'nlocals', 'stack_max', 'nparams',
                          'simple_params', 'catches[*]', 'paths[*]']

    def __init__(self, name, code, consts, iseqs, callinfos, nlocals,
                 stack_max, nparams=0, simple_params=True, catches=None,
                 paths=None):
        self.name = name
        self.code = code
        # VALUEs built at load time; gcroots keeps them reachable.
        self.consts = consts
        self.iseqs = iseqs
        self.callinfos = callinfos
        self.nlocals = nlocals
        self.stack_max = stack_max
        # Required parameters, which YARV puts in locals[0:nparams] in order.
        self.nparams = nparams
        # False once the loader saw any other parameter kind; the call path
        # refuses those rather than guessing.
        self.simple_params = simple_params
        # rescue/ensure entries in CRuby's search order; the first match wins.
        self.catches = catches if catches is not None else []
        self.paths = paths if paths is not None else []

    def repr(self):
        return '<W_ISeq %s>' % self.name


class W_CallInfo(object):
    _immutable_fields_ = ['mid', 'argc', 'simple', 'fcall', 'is_super']

    def __init__(self, mid, argc, simple=True, fcall=True, is_super=False):
        # invokesuper's call data names no method: the running one is implied.
        self.is_super = is_super
        self.mid = mid
        self.argc = argc
        # False once the loader saw call flags outside SIMPLE_CALL_FLAGS.
        self.simple = simple
        # A receiverless call, or an explicit `self.`: may reach a private one.
        self.fcall = fcall

    def repr(self):
        return '<W_CallInfo %s argc=%d>' % (symbols.name_of(self.mid),
                                            self.argc)
