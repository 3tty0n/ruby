"""Front end over an embedded CRuby: iseqw.to_a -> rawiseq objects.

Only this module and boot.py pull in rpython.rtyper; the loader, the
interpreter and their tests stay importable on plain CPython.
"""

import boot
import rawiseq

ISEQ_MAGIC = 'YARVInstructionSequence/SimpleDataFormat'
EVENT_PREFIX = 'RUBY_EVENT_'

# Indices into to_a, as iseq_data_to_ary builds it.
I_MISC = 4
I_LABEL = 5
I_TYPE = 9
I_LOCALS = 10
I_PARAMS = 11
I_CATCH = 12
I_BODY = 13


def is_iseq(v):
    if not boot.is_array(v):
        return False
    if boot.ary_len(v) < 1:
        return False
    head = boot.ary_entry(v, 0)
    return boot.is_string(head) and boot.str_of(head) == ISEQ_MAGIC


def load(iseqw):
    """A RawProgram whose iseq 0 is iseqw."""
    program = rawiseq.RawProgram('', _path(iseqw))
    pending = [boot.call0(iseqw, 'to_a')]
    i = 0
    while i < len(pending):
        _read_iseq(program, pending, pending[i])
        i += 1
    return program


def _path(iseqw):
    v = boot.call0(iseqw, 'absolute_path')
    if boot.is_string(v):
        return boot.str_of(v)
    return ''


def _read_iseq(program, pending, ary):
    misc = boot.ary_entry(ary, I_MISC)
    params = boot.ary_entry(ary, I_PARAMS)
    raw = rawiseq.RawISeq(
        boot.str_of(boot.ary_entry(ary, I_LABEL)),
        boot.sym_of(boot.ary_entry(ary, I_TYPE)),
        boot.ary_len(boot.ary_entry(ary, I_LOCALS)),
        _int_or(boot.hash_aref(misc, 'stack_max'), 0),
        _int_or(boot.hash_aref(params, 'lead_num'), 0),
        _extra_params(params),
        boot.ary_len(boot.ary_entry(ary, I_CATCH)))
    program.add_iseq(raw)

    body = boot.ary_entry(ary, I_BODY)
    n = boot.ary_len(body)
    i = 0
    while i < n:
        e = boot.ary_entry(body, i)
        i += 1
        if boot.is_array(e):
            raw.add_insn(_insn(pending, e))
        elif boot.is_symbol(e):
            name = boot.sym_of(e)
            if not name.startswith(EVENT_PREFIX):
                raw.add_label(name)


def _insn(pending, e):
    operands = []
    n = boot.ary_len(e)
    i = 1
    while i < n:
        operands.append(_operand(pending, boot.ary_entry(e, i)))
        i += 1
    return rawiseq.RawInsn(boot.sym_of(boot.ary_entry(e, 0)), operands)


def _operand(pending, v):
    if boot.is_fixnum(v):
        return rawiseq.int_operand(boot.num2long(v))
    if boot.is_nil(v):
        return rawiseq.RawOperand(rawiseq.OP_NIL)
    if boot.is_true(v):
        return rawiseq.RawOperand(rawiseq.OP_TRUE)
    if boot.is_false(v):
        return rawiseq.RawOperand(rawiseq.OP_FALSE)
    if boot.is_symbol(v):
        return rawiseq.RawOperand(rawiseq.OP_SYM, 0, boot.sym_of(v))
    if boot.is_string(v):
        return rawiseq.RawOperand(rawiseq.OP_STR, 0, boot.str_of(v))
    if boot.is_array(v):
        if is_iseq(v):
            pending.append(v)
            return rawiseq.RawOperand(rawiseq.OP_ISEQ, len(pending) - 1)
        items = []
        n = boot.ary_len(v)
        i = 0
        while i < n:
            items.append(_operand(pending, boot.ary_entry(v, i)))
            i += 1
        return rawiseq.RawOperand(rawiseq.OP_ARRAY, 0, '', 0, False, items)
    if boot.is_hash(v):
        mid = boot.hash_aref(v, 'mid')
        argc = boot.hash_aref(v, 'orig_argc')
        if boot.is_symbol(mid) and not boot.is_nil(argc):
            return rawiseq.RawOperand(
                rawiseq.OP_CALL, boot.num2long(argc), boot.sym_of(mid),
                _int_or(boot.hash_aref(v, 'flag'), 0),
                not boot.is_nil(boot.hash_aref(v, 'kw_arg')))
    return rawiseq.RawOperand(rawiseq.OP_OTHER, 0, boot.inspect(v))


def _int_or(v, default):
    if boot.is_nil(v):
        return default
    return boot.num2long(v)


def _extra_params(params):
    names = []
    keys = boot.call0(params, 'keys')
    n = boot.ary_len(keys)
    i = 0
    while i < n:
        name = boot.sym_of(boot.ary_entry(keys, i))
        if name != 'lead_num':
            names.append(name)
        i += 1
    return ','.join(names)
