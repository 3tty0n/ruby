"""Join insns.py's facts with yarv_map.py's decisions, indexed by opcode."""

import insns
import yarv_map

_N = insns.INSTRUCTION_COUNT

IMPLEMENTED = [False] * _N

EMIT_POSITIONS = []
NUM_OPERANDS = [0] * _N
for _i in range(_N):
    EMIT_POSITIONS.append([])

for _name in yarv_map.EMIT:
    _op = insns.NAME_TO_OP[_name]
    _pos = yarv_map.EMIT[_name]
    IMPLEMENTED[_op] = True
    EMIT_POSITIONS[_op] = _pos[:]
    NUM_OPERANDS[_op] = len(_pos)

SUPPORTED_TYPES = [False] * len(insns.TYPE_NAMES)
DISCARDED_TYPES = [False] * len(insns.TYPE_NAMES)
for _i in range(len(insns.TYPE_NAMES)):
    _t = insns.TYPE_NAMES[_i]
    SUPPORTED_TYPES[_i] = _t in yarv_map.SUPPORTED_OPERAND_TYPES
    DISCARDED_TYPES[_i] = _t in yarv_map.DISCARDED_OPERAND_TYPES

MAX_LOCAL_LEVEL = yarv_map.MAX_LOCAL_LEVEL
ENV_DATA_SIZE = yarv_map.ENV_DATA_SIZE
SIMPLE_CALL_FLAGS = yarv_map.SIMPLE_CALL_FLAGS
CALL_FLAG_ARGS_SIMPLE = yarv_map.CALL_FLAG_ARGS_SIMPLE
CALL_FLAG_FCALL = yarv_map.CALL_FLAG_FCALL
DEFINECLASS_TYPE_MASK = yarv_map.DEFINECLASS_TYPE_MASK
DEFINECLASS_TYPE_CLASS = yarv_map.DEFINECLASS_TYPE_CLASS
DEFINECLASS_FLAG_SCOPED = yarv_map.DEFINECLASS_FLAG_SCOPED
DEFINECLASS_FLAG_HAS_SUPERCLASS = yarv_map.DEFINECLASS_FLAG_HAS_SUPERCLASS
SPECIAL_OBJECT_CONST_BASE = yarv_map.SPECIAL_OBJECT_CONST_BASE
