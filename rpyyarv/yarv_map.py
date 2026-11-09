"""Which YARV instructions RPyYARV implements, and how it encodes them.

Hand-written on purpose: insns.py holds facts derived from insns.def, this
file holds the decisions. rpyvmgen/verify.rb cross-checks the two and
optable.py joins them. Anything absent from EMIT is unsupported, and the
loader must fail loudly rather than skip, so the missing-instruction counter
drives what to implement next.
"""

# YARV name -> the operand positions the loader emits, in order. Positions
# left out are consumed at load time: checked, folded into another operand,
# or dropped. Every emitted position becomes exactly one int in W_ISeq.code,
# so the length is the instruction's width; an operand carrying more than an
# int (VALUE, ISEQ, CALL_DATA) goes into the constant pool and the code
# stream holds its index.
EMIT = {
    'nop': [],
    'putnil': [],
    'putself': [],
    'putspecialobject': [0],    # type is checked: VMCORE, CBASE, CONST_BASE
    'putobject': [0],
    'putchilledstring': [0],
    'newarray': [0],
    'duparray': [0],
    'newhash': [0],
    'duphash': [0],
    'splatarray': [0],
    'concattoarray': [],
    'pushtoarray': [0],
    'newrange': [0],
    'getlocal': [0, 1],
    'setlocal': [0, 1],
    'getblockparam': [1],       # index dropped: the Proc is the frame's block
    'getblockparamproxy': [1],
    'getinstancevariable': [0],     # IVC dropped
    'setinstancevariable': [0],
    'getglobal': [0],
    'setglobal': [0],
    'dup': [],
    'pop': [],
    'swap': [],
    'topn': [0],
    'setn': [0],
    'dupn': [0],
    'opt_reverse': [0],
    'adjuststack': [0],
    'expandarray': [0],     # flag is checked, only plain masgn
    'opt_plus': [],         # CALL_DATA dropped
    'opt_minus': [],
    'opt_mult': [],
    'opt_div': [],
    'opt_mod': [],
    'opt_lt': [],
    'opt_gt': [],
    'opt_le': [],
    'opt_ge': [],
    'opt_eq': [],
    'opt_neq': [],
    'opt_not': [],
    'opt_aref': [],
    'opt_aset': [],
    'opt_length': [],
    'opt_size': [],
    'opt_empty_p': [],
    'objtostring': [],      # CALL_DATA dropped: to_s is resolved inline
    'opt_case_dispatch': [],    # table dropped: the === sends after it decide
    'anytostring': [],
    'concatstrings': [0],
    'jump': [0],
    'branchif': [0],
    'branchunless': [0],
    'definemethod': [0, 1],
    'definesmethod': [0, 1],
    'defineclass': [0, 1, 2],   # type is checked, only a class
    'opt_send_without_block': [0],
    'send': [0, 1],         # blockiseq is iseq.NO_BLOCK_ISEQ when absent
    'invokeblock': [0],
    'invokesuper': [0, 1],      # blockiseq is iseq.NO_BLOCK_ISEQ when absent
    'opt_new': [0, 1],          # falls back to a plain send of new at 1
    'opt_getconstant_path': [0],
    'setconstant': [0],
    'leave': [],
}

# Operand types the loader knows how to transform. Any other type in an
# implemented instruction means it would silently mis-decode it.
#
#   VALUE      -> constant pool index
#   lindex_t   -> EP-relative index to a 0-based local slot
#   OFFSET     -> label to an absolute pc
#   rb_num_t   -> plain integer
#   ID         -> interned id (symbols.py)
#   ISEQ       -> nested iseq loaded recursively, constant pool index
#   CALL_DATA  -> W_CallInfo(mid, orig_argc) in the constant pool, index
#                 emitted. Flags outside SIMPLE_CALL_FLAGS must clear
#                 W_CallInfo.simple so the call fails loudly.
#   IC         -> opt_getconstant_path's names as a W_ConstPath in the
#                 constant pool, index emitted
SUPPORTED_OPERAND_TYPES = frozenset([
    'VALUE',
    'lindex_t',
    'rb_num_t',
    'OFFSET',
    'ID',
    'ISEQ',
    'CALL_DATA',
    'IC',
])

# Operands the loader drops: CRuby's inline caches, which the meta-tracing
# JIT is meant to rediscover.
DISCARDED_OPERAND_TYPES = frozenset([
    'IVC',
    'ICVARC',
    'ISE',
])

# vm_core.h. A lindex_t operand counts down from the top of the environment:
#     slot = nlocals - operand + ENV_DATA_SIZE - 1
ENV_DATA_SIZE = 3

# vm_core.h. putspecialobject's VMCORE receives alias and undef, CBASE is where
# they apply and CONST_BASE where class and constant definitions land;
# defineclass's flags give the kind of definition.
SPECIAL_OBJECT_VMCORE = 1
SPECIAL_OBJECT_CBASE = 2
SPECIAL_OBJECT_CONST_BASE = 3
DEFINECLASS_TYPE_MASK = 0x07
DEFINECLASS_FLAG_HAS_SUPERCLASS = 0x10

# variable.c. The global variables CRuby defines itself, with hooks on reading
# and writing, as global_variables lists them at startup.
CRUBY_GLOBALS = frozenset([
    '$!', '$"', '$$', '$&', "$'", '$*', '$+', '$,', '$-0', '$-F', '$-I',
    '$-W', '$-a', '$-d', '$-i', '$-l', '$-p', '$-v', '$-w', '$.', '$/', '$0',
    '$:', '$;', '$<', '$=', '$>', '$?', '$@', '$DEBUG', '$FILENAME',
    '$LOADED_FEATURES', '$LOAD_PATH', '$PROGRAM_NAME', '$VERBOSE', '$\\',
    '$_', '$`', '$stderr', '$stdin', '$stdout', '$~',
])

# object.c and kernel.rb. What CRuby's Object answers, public or private, as
# Object.instance_methods + Object.private_instance_methods lists them.
CRUBY_OBJECT_METHODS = frozenset([
    '!', '!=', '!~', '<=>', '==', '===', 'Array', 'Complex', 'Float', 'Hash',
    'Integer', 'Pathname', 'Rational', 'String', '__callee__', '__dir__',
    '__id__', '__method__', '__send__', '`', 'abort', 'at_exit', 'autoload',
    'autoload?', 'binding', 'block_given?', 'caller', 'caller_locations',
    'catch', 'class', 'clone', 'define_singleton_method', 'display', 'dup',
    'enum_for', 'eql?', 'equal?', 'eval', 'exec', 'exit', 'exit!', 'extend',
    'fail', 'fork', 'format', 'freeze', 'frozen?', 'gets', 'global_variables',
    'hash', 'initialize', 'initialize_clone', 'initialize_copy',
    'initialize_dup', 'inspect', 'instance_eval', 'instance_exec',
    'instance_of?', 'instance_variable_defined?', 'instance_variable_get',
    'instance_variable_set', 'instance_variables',
    'instance_variables_to_inspect', 'is_a?', 'iterator?', 'itself',
    'kind_of?', 'lambda', 'load', 'local_variables', 'loop', 'method',
    'method_missing', 'methods', 'nil?', 'object_id', 'open', 'p', 'pp',
    'print', 'printf', 'private_methods', 'proc', 'protected_methods',
    'public_method', 'public_methods', 'public_send', 'putc', 'puts', 'raise',
    'rand', 'readline', 'readlines', 'remove_instance_variable', 'require',
    'require_relative', 'respond_to?', 'respond_to_missing?', 'select', 'send',
    'set_trace_func', 'singleton_class', 'singleton_method',
    'singleton_method_added', 'singleton_method_removed',
    'singleton_method_undefined', 'singleton_methods', 'sleep', 'spawn',
    'sprintf', 'srand', 'syscall', 'system', 'tap', 'test', 'then', 'throw',
    'to_enum', 'to_s', 'trace_var', 'trap', 'untrace_var', 'warn',
    'yield_self',
])

# vm_callinfo.h. Outside this mask (splat, block argument, keywords, super,
# forwarding) the arguments reach the callee differently; ARGS_SIMPLE is
# CRuby's own statement that none of them apply.
CALL_FLAG_ARGS_SPLAT = 0x01
CALL_FLAG_ARGS_BLOCKARG = 0x02
CALL_FLAG_FCALL = 0x04
CALL_FLAG_VCALL = 0x08
CALL_FLAG_ARGS_SIMPLE = 0x10
CALL_FLAG_TAILCALL = 0x80
CALL_FLAG_SUPER = 0x100
CALL_FLAG_ZSUPER = 0x200
CALL_FLAG_ARGS_SPLAT_MUT = 0x1000
SIMPLE_CALL_FLAGS = (CALL_FLAG_FCALL | CALL_FLAG_VCALL |
                     CALL_FLAG_ARGS_SIMPLE | CALL_FLAG_TAILCALL)
SUPER_CALL_FLAGS = CALL_FLAG_SUPER | CALL_FLAG_ZSUPER
SPLAT_CALL_FLAGS = CALL_FLAG_ARGS_SPLAT | CALL_FLAG_ARGS_SPLAT_MUT
