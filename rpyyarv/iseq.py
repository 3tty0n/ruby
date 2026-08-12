"""W_ISeq.code is a flat list of ints; operands that aren't already ints go into type-split pools since `consts` holds raw VALUEs an int list can't hold."""

from rpyyarv import symbols

# A `send` whose call site has no block. Pool indices are >= 0.
NO_BLOCK_ISEQ = -1

# The catch-table entry kinds RPyYARV interprets; see loader.py for the rest.
CATCH_RESCUE = 1
CATCH_ENSURE = 2


class W_Catch(object):
    """One catch-table entry; it covers a pc when start < epc <= end, epc being the pc *after* the raising instruction (vm.c:2911)."""
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
    # Nothing appends after the loader, so the JIT may fold code[pc] and consts[idx] away when pc and iseq are green.
    _immutable_fields_ = ['name', 'code[*]', 'consts[*]', 'iseqs[*]',
                          'callinfos[*]', 'nlocals', 'stack_max', 'nparams',
                          'simple_params', 'catches[*]', 'paths[*]',
                          'path_sites[*]', 'case_tables[*]',
                          'opt_table[*]', 'rest_start', 'post_start',
                          'post_num', 'unsupported', 'autosplat',
                          'has_return_throw', 'catches_return',
                          'kw_table[*]', 'kw_defaults[*]', 'kw_required',
                          'kw_start', 'kw_bits', 'kwrest', 'path']
    # once_cache is written once per body and is deliberately not immutable.

    def __init__(self, name, code, consts, iseqs, callinfos, nlocals,
                 stack_max, nparams=0, simple_params=True, catches=None,
                 paths=None, opt_table=None, rest_start=-1, post_start=-1,
                 post_num=0, unsupported='', autosplat=False,
                 has_return_throw=False, catches_return=False,
                 path_sites=None, kw_table=None, kw_defaults=None,
                 kw_required=0, kw_start=-1, kw_bits=-1, kwrest=-1, path='',
                 case_tables=None):
        # The file this ISeq was compiled from; require_relative in a method body resolves against it, since no CRuby frame carries it.
        self.path = path
        self.name = name
        self.code = code
        # VALUEs built at load time; gcroots keeps them reachable.
        self.consts = consts
        self.iseqs = iseqs
        self.callinfos = callinfos
        self.nlocals = nlocals
        self.stack_max = stack_max
        # Leading required parameters, which YARV puts in locals[0:nparams].
        self.nparams = nparams
        # False once the loader saw anything but leading required parameters;
        # the call path then walks the full shape below.
        self.simple_params = simple_params
        # One start pc per number of optionals given (vm_args.c:906), empty
        # when the ISeq takes none.
        self.opt_table = opt_table if opt_table is not None else []
        # Local slots for *rest and the post parameters; -1 when absent.
        self.rest_start = rest_start
        self.post_start = post_start
        self.post_num = post_num
        # Non-empty when the loader could not represent this ISeq at all.
        self.unsupported = unsupported
        # A single yielded Array spreads over these parameters (vm_args.c:855).
        self.autosplat = autosplat
        # This ISeq or one nested in it says `return` from a block.
        self.has_return_throw = has_return_throw
        # ...and this one is the method (or toplevel) such a return names, so execute() has to catch it. Green, so the check folds away.
        self.catches_return = catches_return
        # Keyword parameter names as symbol ids, the required ones first.
        self.kw_table = kw_table if kw_table is not None else []
        # Parallel to kw_table; Q_UNDEF where the body computes the default.
        self.kw_defaults = kw_defaults if kw_defaults is not None else []
        self.kw_required = kw_required
        # Local slots: the keywords sit at kw_start, the unspecified-optionals
        # mask at kw_bits, and **rest at kwrest; -1 when the kind is absent.
        self.kw_start = kw_start
        self.kw_bits = kw_bits
        self.kwrest = kwrest
        # rescue/ensure entries in CRuby's search order; the first match wins.
        self.catches = catches if catches is not None else []
        self.paths = paths if paths is not None else []
        # One inline cache slot per entry of paths, parallel to it.
        self.path_sites = path_sites if path_sites is not None else []
        # One slot per nested ISeq; `once` fills its body's, Q_UNDEF meaning unrun.
        self.once_cache = [0x24] * len(self.iseqs)
        # Integer literal -> destination pc for opt_case_dispatch.
        self.case_tables = case_tables if case_tables is not None else []

    def repr(self):
        return '<W_ISeq %s>' % self.name


class W_CallInfo(object):
    _immutable_fields_ = ['mid', 'argc', 'simple', 'fcall', 'is_super',
                          'blockarg', 'kw_names[*]', 'kw_splat', 'splat']

    def __init__(self, mid, argc, simple=True, fcall=True, is_super=False,
                 blockarg=False, kw_names=None, kw_splat=False, splat=False):
        # VM_CALL_ARGS_SPLAT: the last positional is an Array to spread there.
        self.splat = splat
        # VM_CALL_KWARG: the last len(kw_names) of the argc values on the stack are keyword values, named here in push order.
        self.kw_names = kw_names if kw_names is not None else []
        # VM_CALL_KW_SPLAT: instead, the topmost argument is a Hash of them.
        self.kw_splat = kw_splat
        # CALL_FLAG_ARGS_BLOCKARG: one more value above the arguments, which vm_caller_setup_arg_block pops first (vm_args.c:1119).
        self.blockarg = blockarg
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
