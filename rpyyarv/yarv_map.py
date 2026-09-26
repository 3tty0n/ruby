"""Anything absent from EMIT is unsupported; the loader fails loudly."""

# vm_core.h and vm_callinfo.h values, generated per host (host/hostconsts.c).
from rpyyarv.hostconsts import (
    ENV_DATA_SIZE, CALL_FLAG_ARGS_SPLAT, CALL_FLAG_ARGS_BLOCKARG,
    CALL_FLAG_KWARG, CALL_FLAG_KW_SPLAT, CALL_FLAG_OPT_SEND,
    CALL_FLAG_KW_SPLAT_MUT, CALL_FLAG_ARGS_SPLAT_MUT, CALL_FLAG_FORWARDING,
    CALL_FLAG_FCALL, CALL_FLAG_VCALL, CALL_FLAG_ARGS_SIMPLE,
    CALL_FLAG_TAILCALL, CALL_FLAG_SUPER, CALL_FLAG_ZSUPER,
    KW_SPECIFIED_BITS_MAX, DEFINECLASS_TYPE_MASK, DEFINECLASS_TYPE_CLASS,
    DEFINECLASS_TYPE_SINGLETON_CLASS, DEFINECLASS_TYPE_MODULE,
    DEFINECLASS_FLAG_SCOPED, DEFINECLASS_FLAG_HAS_SUPERCLASS,
    SPECIAL_OBJECT_VMCORE, SPECIAL_OBJECT_CBASE, SPECIAL_OBJECT_CONST_BASE,
    CHECKMATCH_TYPE_MASK, CHECKMATCH_ARRAY, CHECKMATCH_TYPE_WHEN,
    CHECKMATCH_TYPE_CASE, CHECKMATCH_TYPE_RESCUE, TAG_MASK, TAG_NONE,
    TAG_RETURN, TAG_BREAK, TAG_NEXT, TAG_RETRY, TAG_REDO, NEWARRAY_SEND_MAX,
    NEWARRAY_SEND_MIN, NEWARRAY_SEND_HASH, NEWARRAY_SEND_PACK,
    NEWARRAY_SEND_PACK_BUFFER, NEWARRAY_SEND_INCLUDE_P)

# YARV name -> operand positions emitted as ints; the rest go to the pool.
EMIT = {
    'nop': [],
    'putnil': [],
    'putself': [],
    'putobject': [0],
    'putstring': [0],
    'putchilledstring': [0],
    'getlocal': [0],        # level is packed into the slot, see LOCAL_*
    'setlocal': [0],
    'getblockparam': [0],
    'setblockparam': [0],
    'getblockparamproxy': [0],
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
    'splatkw': [],
    'pushtoarray': [0],
    'concatarray': [],
    'concattoarray': [],
    'opt_regexpmatch2': [],  # CALL_DATA dropped: the fallback is a =~ send
    'opt_duparray_send': [0, 1, 2],
    'opt_and': [],          # CALL_DATA dropped
    'opt_or': [],
    'newrange': [0],
    'getglobal': [0],
    'setglobal': [0],
    'getspecial': [0, 1],   # $~ and its captures; CRuby owns the backref
    'opt_aref': [],
    'opt_aset': [],
    'opt_length': [],
    'opt_size': [],
    'opt_empty_p': [],
    'opt_not': [],
    'opt_ltlt': [],
    'opt_nil_p': [],
    'opt_succ': [],
    'opt_str_freeze': [0],  # the literal, frozen once at load time
    'opt_str_uminus': [0],  # the literal; interned at each execution
    'opt_ary_freeze': [0],
    'opt_hash_freeze': [0],
    'opt_case_dispatch': [0, 1],
    'opt_newarray_send': [0, 1],
    'expandarray': [0, 1],  # count and the splat/post flag
    'opt_plus': [],
    'opt_minus': [],
    'opt_mult': [],
    'opt_lt': [],
    'opt_gt': [],
    'opt_le': [],
    'opt_ge': [],
    'opt_eq': [],
    'opt_div': [],
    'opt_mod': [],
    'opt_neq': [],
    'getinstancevariable': [0],     # IVC dropped
    'setinstancevariable': [0],
    'getclassvariable': [0],        # ICVARC dropped
    'setclassvariable': [0],
    'once': [0],                    # IC dropped: one cache slot per body ISeq
    'defined': [0, 1, 2],
    'definedivar': [0, 2],          # IVC dropped
    'getconstant': [0],             # dynamic A::B; base and flag on the stack
    'opt_getconstant_path': [0],    # IC carries the constant path segments
    'setconstant': [0],
    'putspecialobject': [0],
    'defineclass': [0, 1, 2],
    'opt_new': [0, 1],
    'objtostring': [],      # CALL_DATA dropped: to_s is resolved inline
    'anytostring': [],
    'concatstrings': [0],
    'toregexp': [0, 1],     # options and number of interpolated fragments
    'intern': [],            # interpolated Symbol
    'jump': [0],
    'branchif': [0],
    'branchunless': [0],
    'branchnil': [0],
    'definemethod': [0, 1],
    'definesmethod': [0, 1],
    'opt_send_without_block': [0],
    'send': [0, 1],         # blockiseq is iseq.NO_BLOCK_ISEQ when absent
    'sendforward': [0, 1],
    'invokesuper': [0, 1],
    'invokesuperforward': [0, 1],
    'invokeblock': [0],
    'throw': [0],
    'checkmatch': [0],      # a rescue clause's class test, and case/when
    'checkkeyword': [0, 1], # slot of the kwbits local, then the optional's bit
    'leave': [],
}

# Operand types the loader can transform; anything else is mis-decoded silently.
SUPPORTED_OPERAND_TYPES = frozenset([
    'VALUE',
    'lindex_t',
    'rb_num_t',
    'OFFSET',
    'ID',
    'ISEQ',
    'CALL_DATA',
    'IC',
    'CDHASH',
])

# CRuby's inline caches, which the meta-tracing JIT rediscovers instead.
DISCARDED_OPERAND_TYPES = frozenset([
    'IVC',
    'ICVARC',
    'ISE',
])

# The block-chain walk must stay bounded for the tracer to unroll it.
MAX_LOCAL_LEVEL = 16

# getlocal/setlocal pack slot and level into one operand; no 2**20 locals.
LOCAL_LEVEL_SHIFT = 20
LOCAL_SLOT_MASK = (1 << LOCAL_LEVEL_SHIFT) - 1

# Which unsupported flag a call site carries, most informative first.
CALL_FLAG_NAMES = [
    (CALL_FLAG_FORWARDING, '...'),
    (CALL_FLAG_ARGS_SPLAT, '*splat'),
    (CALL_FLAG_ARGS_BLOCKARG, '&block'),
    (CALL_FLAG_KWARG, 'keyword'),
    (CALL_FLAG_KW_SPLAT, '**keyword splat'),
    (CALL_FLAG_OPT_SEND, 'send'),
]

# Non-SIMPLE args arrive otherwise; SUPER/ZSUPER push the parameters the same
# way, and ARGS_BLOCKARG args arrive plainly with the block on top.
SIMPLE_CALL_FLAGS = (CALL_FLAG_FCALL | CALL_FLAG_VCALL |
                     CALL_FLAG_ARGS_SIMPLE | CALL_FLAG_TAILCALL |
                     CALL_FLAG_SUPER | CALL_FLAG_ZSUPER |
                     CALL_FLAG_ARGS_BLOCKARG)

# ...plus keywords above the positionals, or a **splat Hash on top.
KWARG_CALL_FLAGS = (SIMPLE_CALL_FLAGS | CALL_FLAG_KWARG |
                    CALL_FLAG_KW_SPLAT | CALL_FLAG_KW_SPLAT_MUT)

# ...plus a *splat Array as the last positional (MUT: the Array is fresh).
SPLAT_CALL_FLAGS = (KWARG_CALL_FLAGS | CALL_FLAG_ARGS_SPLAT |
                    CALL_FLAG_ARGS_SPLAT_MUT)

# vm_core.h vm_opt_newarray_send_type: argc by method-1, -1 = no PACK_BUFFER.
NEWARRAY_SEND_ARGC = [0] * 6
for _m, _argc in [(NEWARRAY_SEND_MAX, 0), (NEWARRAY_SEND_MIN, 0),
                  (NEWARRAY_SEND_HASH, 0), (NEWARRAY_SEND_PACK, 1),
                  (NEWARRAY_SEND_PACK_BUFFER, 2),
                  (NEWARRAY_SEND_INCLUDE_P, 1)]:
    NEWARRAY_SEND_ARGC[_m - 1] = _argc
