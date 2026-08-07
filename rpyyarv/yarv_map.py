"""Which YARV instructions RPyYARV implements, and how it encodes them.

insns.py holds the facts derived from insns.def, this file the decisions;
rpyvmgen/verify.rb cross-checks the two and optable.py joins them. Anything
absent from EMIT is unsupported, and the loader fails loudly, never skips.
"""

# YARV name -> the operand positions the loader emits, one int each in
# W_ISeq.code; positions left out are consumed at load time. An operand
# carrying more than an int goes into the constant pool and the code stream
# holds its index.
EMIT = {
    'nop': [],
    'putnil': [],
    'putself': [],
    'putobject': [0],
    'putstring': [0],
    'putchilledstring': [0],
    'getlocal': [0],        # level is packed into the slot, see LOCAL_*
    'setlocal': [0],
    'dup': [],
    'pop': [],
    'swap': [],
    'setn': [0],
    'dupn': [0],
    'topn': [0],
    'adjuststack': [0],
    'opt_reverse': [0],
    'newarray': [0],
    'duparray': [0],
    'newhash': [0],
    'duphash': [0],
    'splatarray': [0],      # the flag is a Qtrue/Qfalse VALUE operand
    'opt_and': [],          # CALL_DATA dropped
    'opt_or': [],
    'newrange': [0],
    'getglobal': [0],
    'setglobal': [0],
    'opt_aref': [],         # CALL_DATA dropped
    'opt_aset': [],
    'opt_length': [],
    'opt_size': [],
    'opt_empty_p': [],
    'opt_not': [],
    'opt_ltlt': [],
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
    'invokesuper': [0, 1],
    'invokeblock': [0],
    'throw': [0],
    'checkmatch': [0],      # a rescue clause's class test, and case/when
    'leave': [],
}

# Operand types the loader knows how to transform; any other type in an
# implemented instruction would be silently mis-decoded.
#   VALUE      -> constant pool index
#   lindex_t   -> EP-relative index to a 0-based local slot
#   OFFSET     -> label to an absolute pc
#   rb_num_t   -> plain integer
#   ID         -> interned id (symbols.py)
#   ISEQ       -> nested iseq loaded recursively, constant pool index
#   CALL_DATA  -> W_CallInfo in the constant pool; flags outside
#                 SIMPLE_CALL_FLAGS must clear W_CallInfo.simple
#   IC         -> the constant path's segments (iseq.c)
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

# CRuby's inline caches, which the meta-tracing JIT rediscovers instead.
DISCARDED_OPERAND_TYPES = frozenset([
    'IVC',
    'ICVARC',
    'ISE',
])

# The block-chain walk must stay bounded for the tracer to unroll it.
MAX_LOCAL_LEVEL = 16

# getlocal/setlocal pack slot and level into one operand, so level 0 is just
# "the operand equals its own slot bits". No scope has 2**20 locals.
LOCAL_LEVEL_SHIFT = 20
LOCAL_SLOT_MASK = (1 << LOCAL_LEVEL_SHIFT) - 1

# vm_core.h. A lindex_t operand counts down from the top of the environment:
#     slot = nlocals - operand + ENV_DATA_SIZE - 1
ENV_DATA_SIZE = 3

# vm_callinfo.h. Outside this mask (splat, block argument, keywords,
# forwarding) the arguments reach the callee differently.
CALL_FLAG_FCALL = 0x04
CALL_FLAG_VCALL = 0x08
CALL_FLAG_ARGS_SIMPLE = 0x10
CALL_FLAG_TAILCALL = 0x80
# invokesuper only; a bare `super` (ZSUPER) pushes the parameters the same way.
CALL_FLAG_SUPER = 0x100
CALL_FLAG_ZSUPER = 0x200
SIMPLE_CALL_FLAGS = (CALL_FLAG_FCALL | CALL_FLAG_VCALL |
                     CALL_FLAG_ARGS_SIMPLE | CALL_FLAG_TAILCALL |
                     CALL_FLAG_SUPER | CALL_FLAG_ZSUPER)

# vm_core.h. Only a plain `class Foo`: no module, singleton class or A::B.
DEFINECLASS_TYPE_MASK = 0x07
DEFINECLASS_TYPE_CLASS = 0x00
DEFINECLASS_FLAG_SCOPED = 0x08
DEFINECLASS_FLAG_HAS_SUPERCLASS = 0x10

# vm_core.h, enum vm_special_object_type.
SPECIAL_OBJECT_VMCORE = 1
SPECIAL_OBJECT_CBASE = 2
SPECIAL_OBJECT_CONST_BASE = 3

# vm_core.h, enum vm_check_match_type. WHEN answers the pattern itself, CASE
# and RESCUE run `pattern === target`; ARRAY means an Array of patterns.
CHECKMATCH_TYPE_MASK = 0x03
CHECKMATCH_TYPE_WHEN = 1
CHECKMATCH_TYPE_CASE = 2
CHECKMATCH_TYPE_RESCUE = 3
CHECKMATCH_ARRAY = 0x04

# vm_core.h, enum ruby_tag_type. Tag 0 continues the throw already in flight.
TAG_MASK = 0xf
TAG_NONE = 0
TAG_RETURN = 1
TAG_BREAK = 2
TAG_NEXT = 3
TAG_RETRY = 4
TAG_REDO = 5
