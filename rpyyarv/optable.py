"""Join generated facts with hand-written decisions, indexed by opcode.

Computed at import time. A name missing from insns.py raises here,
which is the check that insns.py.
"""

import insns
import yarv_map

_N = insns.INSTRUCTION_COUNT

# True where RPyYARV implements the instruction; the loader rejects the rest.
IMPLEMENTED = [False] * _N

# Operand positions the loader emits, and how many words that is. Unimplemented
# instructions keep an empty list, which is never read.
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
