"""Front end over an embedded CRuby: iseqw.to_a -> rawiseq objects."""

# Only this module and boot.py import rpython; the rest stays importable on plain CPython.

import boot
import rawiseq
import to_a_layout
from error import LoadError
from to_a_layout import (I_BODY, I_CATCH, I_LABEL, I_LOCALS, I_MAGIC, I_MISC,
                         I_PARAMS, I_TYPE)

EVENT_PREFIX = 'RUBY_EVENT_'

# Keys of the params hash (iseq.c:3425-3462): use_block is a hint on `initialize` methods (iseq.c:615) not a parameter, ambiguous_param0 only enables block autosplat (unused here), block_start needs no call-path handling until getblockparam(proxy) reads it.
PLAIN_PARAM_KEYS = ['lead_num', 'use_block', 'opt', 'rest_start',
                    'post_start', 'post_num', 'ambiguous_param0',
                    'block_start']

# Anything outside this means the ISeq declares real parameters, so arg_size is not the lead count.
NO_PARAM_KEYS = ['use_block', 'ambiguous_param0']


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
    owners = [-1]
    i = 0
    while i < len(pending):
        _read_iseq(program, pending, owners, pending[i], owners[i])
        i += 1
    return program


def _path(iseqw):
    v = boot.call0(iseqw, 'absolute_path')
    if boot.is_string(v):
        return boot.str_of(v)
    return ''


def _read_iseq(program, pending, owners, ary, parent):
    check(ary)
    misc = boot.ary_entry(ary, I_MISC)
    params = boot.ary_entry(ary, I_PARAMS)
    raw = rawiseq.RawISeq(
        boot.str_of(boot.ary_entry(ary, I_LABEL)),
        boot.sym_of(boot.ary_entry(ary, I_TYPE)),
        boot.ary_len(boot.ary_entry(ary, I_LOCALS)),
        _int_or(boot.hash_aref(misc, 'stack_max'), 0),
        _lead_num(misc, params),
        _extra_params(params),
        _catches(pending, owners, boot.ary_entry(ary, I_CATCH),
                 len(program.iseqs)),
        _opt_labels(params),
        _int_or(boot.hash_aref(params, 'rest_start'), -1),
        _int_or(boot.hash_aref(params, 'post_start'), -1),
        _int_or(boot.hash_aref(params, 'post_num'), 0),
        not boot.is_nil(boot.hash_aref(params, 'ambiguous_param0')))
    raw.parent = parent
    program.add_iseq(raw)

    me = len(program.iseqs) - 1
    body = boot.ary_entry(ary, I_BODY)
    n = boot.ary_len(body)
    i = 0
    while i < n:
        e = boot.ary_entry(body, i)
        i += 1
        if boot.is_array(e):
            raw.add_insn(_insn(pending, owners, e, me))
        elif boot.is_symbol(e):
            name = boot.sym_of(e)
            if not name.startswith(EVENT_PREFIX):
                raw.add_label(name)


def _insn(pending, owners, e, me):
    operands = []
    n = boot.ary_len(e)
    i = 1
    while i < n:
        operands.append(_operand(pending, owners,
                                 boot.ary_entry(e, i), me))
        i += 1
    return rawiseq.RawInsn(boot.sym_of(boot.ary_entry(e, 0)), operands)


def _operand(pending, owners, v, me):
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
            owners.append(me)
            return rawiseq.RawOperand(rawiseq.OP_ISEQ, len(pending) - 1)
        items = []
        n = boot.ary_len(v)
        i = 0
        while i < n:
            items.append(_operand(pending, owners,
                                  boot.ary_entry(v, i), me))
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
    # Float, Range, Regexp and the rest cross as the VALUE itself.
    return rawiseq.RawOperand(rawiseq.OP_VALUE, v, boot.inspect(v))


def _catches(pending, owners, catch, me):
    """An entry's ISeq joins the same pending queue the body's nested ISeqs use; see rawiseq.RawCatch for the layout."""
    out = []
    n = boot.ary_len(catch)
    i = 0
    while i < n:
        e = boot.ary_entry(catch, i)
        if not boot.is_array(e) or boot.ary_len(e) != 6:
            raise LoadError('a catch-table entry has %d element(s), expected '
                            '6: %s' % (boot.ary_len(e), boot.inspect(e)))
        kind = '?'
        t = boot.ary_entry(e, 0)
        if boot.is_symbol(t):
            kind = boot.sym_of(t)
        body = boot.ary_entry(e, 1)
        index = -1
        if not boot.is_nil(body):
            pending.append(body)
            owners.append(me)
            index = len(pending) - 1
        out.append(rawiseq.RawCatch(kind, index,
                                    _label(boot.ary_entry(e, 2)),
                                    _label(boot.ary_entry(e, 3)),
                                    _label(boot.ary_entry(e, 4)),
                                    _int_or(boot.ary_entry(e, 5), 0)))
        i += 1
    return out


def _label(v):
    if not boot.is_symbol(v):
        raise LoadError('a catch-table entry names a pc that is not a label')
    return boot.sym_of(v)


def _lead_num(misc, params):
    """Leading required parameter count: iseq.c:3437 omits lead_num unless flags.has_lead is set, which a `for` block param is not; arg_size counts it either way."""
    if len(_param_keys(params, NO_PARAM_KEYS)) == 0:
        return _int_or(boot.hash_aref(misc, 'arg_size'), 0)
    return _int_or(boot.hash_aref(params, 'lead_num'), 0)


def _opt_labels(params):
    """The opt table as label names; entry i starts the body with i optionals filled (vm_args.c:906)."""
    v = boot.hash_aref(params, 'opt')
    if boot.is_nil(v):
        return []
    out = []
    n = boot.ary_len(v)
    i = 0
    while i < n:
        e = boot.ary_entry(v, i)
        if not boot.is_symbol(e):
            raise LoadError('an opt table entry is not a label')
        out.append(boot.sym_of(e))
        i += 1
    return out


def _int_or(v, default):
    if boot.is_nil(v):
        return default
    return boot.num2long(v)


def _extra_params(params):
    """The parameter kinds RPyYARV cannot place: keyword, kwrest, block and the block-only ambiguous_param0."""
    return ','.join(_param_keys(params, PLAIN_PARAM_KEYS))


def _param_keys(params, known):
    names = []
    keys = boot.call0(params, 'keys')
    n = boot.ary_len(keys)
    i = 0
    while i < n:
        name = boot.sym_of(boot.ary_entry(keys, i))
        if name not in known:
            names.append(name)
        i += 1
    return names
