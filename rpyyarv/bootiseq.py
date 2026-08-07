"""Front end over an embedded CRuby: iseqw.to_a -> rawiseq objects."""

# Only this module and boot.py import rpython; the loader, the interpreter
# and their tests stay importable on plain CPython.

import boot
import rawiseq
import to_a_layout
from error import LoadError
from to_a_layout import (I_BODY, I_CATCH, I_LABEL, I_LOCALS, I_MAGIC, I_MISC,
                         I_PARAMS, I_TYPE)

EVENT_PREFIX = 'RUBY_EVENT_'

# Keys of the params hash that leave the argument layout alone. use_block is
# a hint CRuby sets on every method named initialize (iseq.c:615).
PLAIN_PARAM_KEYS = ['lead_num', 'use_block']


def is_iseq(v):
    if not boot.is_array(v):
        return False
    if boot.ary_len(v) < 1:
        return False
    head = boot.ary_entry(v, 0)
    return boot.is_string(head) and boot.str_of(head) == to_a_layout.MAGIC


def kind_of(v):
    if boot.is_fixnum(v):
        return to_a_layout.K_INTEGER
    if boot.is_string(v):
        return to_a_layout.K_STRING
    if boot.is_symbol(v):
        return to_a_layout.K_SYMBOL
    if boot.is_array(v):
        return to_a_layout.K_ARRAY
    if boot.is_hash(v):
        return to_a_layout.K_HASH
    return boot.inspect(v)


def check(ary):
    """Refuse a to_a whose shape is not the one to_a_layout.py describes."""
    moved = 'iseq_data_to_ary in iseq.c moved a field; update to_a_layout.py'
    n = boot.ary_len(ary)
    if n != to_a_layout.LENGTH:
        raise LoadError('iseqw.to_a has %d elements, expected %d: %s'
                        % (n, to_a_layout.LENGTH, moved))
    for index, kind in to_a_layout.EXPECTED:
        found = kind_of(boot.ary_entry(ary, index))
        if found != kind:
            raise LoadError('iseqw.to_a[%d] holds %s, expected %s: %s'
                            % (index, found, kind, moved))
    magic = boot.str_of(boot.ary_entry(ary, I_MAGIC))
    if magic != to_a_layout.MAGIC:
        raise LoadError('iseqw.to_a[%d] is "%s", expected "%s": %s'
                        % (I_MAGIC, magic, to_a_layout.MAGIC, moved))


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
    check(ary)
    misc = boot.ary_entry(ary, I_MISC)
    params = boot.ary_entry(ary, I_PARAMS)
    raw = rawiseq.RawISeq(
        boot.str_of(boot.ary_entry(ary, I_LABEL)),
        boot.sym_of(boot.ary_entry(ary, I_TYPE)),
        boot.ary_len(boot.ary_entry(ary, I_LOCALS)),
        _int_or(boot.hash_aref(misc, 'stack_max'), 0),
        _int_or(boot.hash_aref(params, 'lead_num'), 0),
        _extra_params(params),
        _catch_types(boot.ary_entry(ary, I_CATCH)))
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
        if not boot.is_nil(argc):
            # invokesuper's call data names no method: the running one is.
            name = ''
            if boot.is_symbol(mid):
                name = boot.sym_of(mid)
            return rawiseq.RawOperand(
                rawiseq.OP_CALL, boot.num2long(argc), name,
                _int_or(boot.hash_aref(v, 'flag'), 0),
                not boot.is_nil(boot.hash_aref(v, 'kw_arg')))
    # Anything else -- Float, Range, Regexp -- crosses as the VALUE itself;
    # the loader pins it and puts it straight into the constant pool.
    return rawiseq.RawOperand(rawiseq.OP_VALUE, v, boot.inspect(v))


def _catch_types(catch):
    """iseq_data_to_ary spells each entry [type, iseq, start, end, cont, sp]."""
    names = []
    n = boot.ary_len(catch)
    i = 0
    while i < n:
        e = boot.ary_entry(catch, i)
        name = '?'
        if boot.is_array(e) and boot.ary_len(e) > 0:
            t = boot.ary_entry(e, 0)
            if boot.is_symbol(t):
                name = boot.sym_of(t)
        names.append(name)
        i += 1
    return names


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
        if name not in PLAIN_PARAM_KEYS:
            names.append(name)
        i += 1
    return ','.join(names)
