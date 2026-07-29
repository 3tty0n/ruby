"""Which YARV instructions RPyYARV implements, and how it encodes them.

Hand-written on purpose. insns.py holds facts derived from insns.def; this
file holds the decisions. rpyvmgen/verify.rb cross-checks the two, and
optable.py joins them into tables indexed by opcode.

Anything absent from EMIT is unsupported. The loader must fail loudly rather
than skip, so that the missing-instruction counter drives what to implement
next.
"""

# YARV name -> the operand positions the loader emits, in order. Positions
# left out are consumed at load time: checked, folded into another operand,
# or dropped. The length is the instruction's width in W_ISeq.code.
EMIT = {
    'nop': [],
    'putnil': [],
    'putobject': [0],
    'getlocal': [0],        # level is checked against MAX_LOCAL_LEVEL
    'setlocal': [0],        # likewise
    'dup': [],
    'pop': [],
    'opt_plus': [],         # CALL_DATA dropped
    'opt_minus': [],
    'opt_mult': [],
    'opt_lt': [],
    'opt_gt': [],
    'opt_le': [],
    'opt_ge': [],
    'opt_eq': [],
    'jump': [0],
    'branchif': [0],
    'branchunless': [0],
    'leave': [],
}

# Operand types we know how to transform. An operand of any other type in a
# supported instruction means the loader would silently mis-decode it.
#
#   VALUE      -> intern into the constant pool, emit its index
#   lindex_t   -> convert EP-relative index to a 0-based local slot
#   OFFSET     -> resolve the label to an absolute pc
#   rb_num_t   -> plain integer
#   CALL_DATA  -> take mid/orig_argc; the inline cache is dropped, since
#                 @elidable plus a version tag regenerates its effect
SUPPORTED_OPERAND_TYPES = frozenset([
    'VALUE',
    'lindex_t',
    'rb_num_t',
    'OFFSET',
    'CALL_DATA',
])

# Operands the loader drops. These are CRuby's inline caches; RPyYARV lets
# the meta-tracing JIT rediscover the same information.
DISCARDED_OPERAND_TYPES = frozenset([
    'IC',
    'IVC',
    'ICVARC',
    'ISE',
])

# Only level 0 is supported until blocks land: a non-zero level reaches an
# enclosing scope. getlocal_WC_0 / setlocal_WC_0 carry that guarantee; the
# _WC_1 variants and any explicit non-zero level must be rejected.
MAX_LOCAL_LEVEL = 0
