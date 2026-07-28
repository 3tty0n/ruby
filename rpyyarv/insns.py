# Dense internal opcode numbering, private to rpyyarv and unrelated to YARV's
# own opcode numbers. A future loader maps YARV instruction names onto these.

NOP = 0
PUTNIL = 1
PUTOBJECT = 2
GETLOCAL = 3
SETLOCAL = 4
DUP = 5
POP = 6
OPT_PLUS = 7
OPT_MINUS = 8
OPT_MULT = 9
OPT_LT = 10
OPT_GT = 11
OPT_LE = 12
OPT_GE = 13
OPT_EQ = 14
JUMP = 15
BRANCHIF = 16
BRANCHUNLESS = 17
LEAVE = 18

NAMES = [
    'nop',
    'putnil',
    'putobject',
    'getlocal',
    'setlocal',
    'dup',
    'pop',
    'opt_plus',
    'opt_minus',
    'opt_mult',
    'opt_lt',
    'opt_gt',
    'opt_le',
    'opt_ge',
    'opt_eq',
    'jump',
    'branchif',
    'branchunless',
    'leave',
]

NUM_OPERANDS = [
    0,  # nop
    0,  # putnil
    1,  # putobject
    1,  # getlocal
    1,  # setlocal
    0,  # dup
    0,  # pop
    0,  # opt_plus
    0,  # opt_minus
    0,  # opt_mult
    0,  # opt_lt
    0,  # opt_gt
    0,  # opt_le
    0,  # opt_ge
    0,  # opt_eq
    1,  # jump
    1,  # branchif
    1,  # branchunless
    0,  # leave
]
