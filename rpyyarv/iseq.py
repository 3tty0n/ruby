"""Loaded code: W_ISeq.code is a flat list of ints.

Operands that are already ints (local slots, branch targets, interned ids)
sit in it directly; everything else goes into one of three pools and the code
stream carries the index. The pools are split by type because `consts` now
holds raw VALUEs -- an RPython list of ints cannot also hold objects.
"""

import symbols

# A `send` whose call site has no block. Pool indices are >= 0.
NO_BLOCK_ISEQ = -1


class W_ISeq(object):
    # The loader hands over finished lists; nothing appends afterwards, so the
    # JIT may fold code[pc] and consts[idx] away when pc and iseq are green.
    _immutable_fields_ = ['name', 'code[*]', 'consts[*]', 'iseqs[*]',
                          'callinfos[*]', 'nlocals', 'stack_max', 'nparams',
                          'simple_params']

    def __init__(self, name, code, consts, iseqs, callinfos, nlocals,
                 stack_max, nparams=0, simple_params=True):
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
        # False once the loader saw optional/rest/post/keyword/block
        # parameters; the call path refuses those rather than guessing.
        self.simple_params = simple_params

    def repr(self):
        return '<W_ISeq %s>' % self.name


class W_CallInfo(object):
    _immutable_fields_ = ['mid', 'argc', 'simple', 'fcall']

    def __init__(self, mid, argc, simple=True, fcall=True):
        self.mid = mid
        self.argc = argc
        # False once the loader saw call flags outside SIMPLE_CALL_FLAGS.
        self.simple = simple
        # A receiverless call, or an explicit `self.`: may reach a private one.
        self.fcall = fcall

    def repr(self):
        return '<W_CallInfo %s argc=%d>' % (symbols.name_of(self.mid),
                                            self.argc)
