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
    'putobject': [0],
    'putstring': [0],
    'putchilledstring': [0],
    'getlocal': [0],        # level is checked against MAX_LOCAL_LEVEL
    'setlocal': [0],        # likewise
    'dup': [],
    'pop': [],
    'swap': [],
    'expandarray': [0],     # flag is checked, only plain masgn
    'opt_plus': [],         # CALL_DATA dropped
    'opt_minus': [],
    'opt_mult': [],
    'opt_lt': [],
    'opt_gt': [],
    'opt_le': [],
    'opt_ge': [],
    'opt_eq': [],
    'opt_div': [],
    'opt_mod': [],
    'opt_neq': [],          # both CALL_DATA dropped
    'getinstancevariable': [0],     # IVC dropped
    'setinstancevariable': [0],
    'opt_getconstant_path': [0],    # IC carries the constant path segments
    'setconstant': [0],
    'putspecialobject': [0],
    'defineclass': [0, 1, 2],
    'opt_new': [0, 1],
    'objtostring': [],      # CALL_DATA dropped: to_s is resolved inline
    'anytostring': [],
    'concatstrings': [0],
    'jump': [0],
    'branchif': [0],
    'branchunless': [0],
    'definemethod': [0, 1],
    'opt_send_without_block': [0],
    'send': [0, 1],         # blockiseq is iseq.NO_BLOCK_ISEQ when absent
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
#   IC         -> iseq_data_to_ary spells it as the constant path segments;
#                 a one-segment path becomes an interned id.
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

# A non-zero level reaches an enclosing scope, so the _WC_1 variants and any
# explicit non-zero level are rejected until blocks land.
MAX_LOCAL_LEVEL = 0

# vm_core.h. A lindex_t operand counts down from the top of the environment:
#     slot = nlocals - operand + ENV_DATA_SIZE - 1
ENV_DATA_SIZE = 3

# vm_callinfo.h. Outside this mask (splat, block argument, keywords, super,
# forwarding) the arguments reach the callee differently; ARGS_SIMPLE is
# CRuby's own statement that none of them apply.
CALL_FLAG_FCALL = 0x04
CALL_FLAG_VCALL = 0x08
CALL_FLAG_ARGS_SIMPLE = 0x10
CALL_FLAG_TAILCALL = 0x80
SIMPLE_CALL_FLAGS = (CALL_FLAG_FCALL | CALL_FLAG_VCALL |
                     CALL_FLAG_ARGS_SIMPLE | CALL_FLAG_TAILCALL)

# vm_core.h. Only a plain `class Foo` is supported: no module, no singleton
# class, no `class A::B`.
DEFINECLASS_TYPE_MASK = 0x07
DEFINECLASS_TYPE_CLASS = 0x00
DEFINECLASS_FLAG_SCOPED = 0x08
DEFINECLASS_FLAG_HAS_SUPERCLASS = 0x10

# vm_core.h, enum vm_special_object_type. Only the cref's constant base,
# which is what `class Foo` and a toplevel constant assignment emit.
SPECIAL_OBJECT_CONST_BASE = 3
