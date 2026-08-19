"""Field positions in iseqw.to_a, as iseq_data_to_ary (iseq.c) pushes them."""

MAGIC = 'YARVInstructionSequence/SimpleDataFormat'
LENGTH = 14

I_MAGIC = 0
I_MAJOR = 1
I_MINOR = 2
I_FORMAT = 3
I_MISC = 4
I_LABEL = 5
I_PATH = 6
I_REALPATH = 7
I_LINENO = 8
I_TYPE = 9
I_LOCALS = 10
I_PARAMS = 11
I_CATCH = 12
I_BODY = 13

K_INTEGER = 'Integer'
K_STRING = 'String'
K_SYMBOL = 'Symbol'
K_ARRAY = 'Array'
K_HASH = 'Hash'

# Enough shape that no single field can move undetected (bootiseq.check()).
EXPECTED = [
    (I_MAGIC, K_STRING),
    (I_MAJOR, K_INTEGER),
    (I_MINOR, K_INTEGER),
    (I_MISC, K_HASH),
    (I_LABEL, K_STRING),
    (I_LINENO, K_INTEGER),
    (I_TYPE, K_SYMBOL),
    (I_LOCALS, K_ARRAY),
    (I_PARAMS, K_HASH),
    (I_CATCH, K_ARRAY),
    (I_BODY, K_ARRAY),
]
