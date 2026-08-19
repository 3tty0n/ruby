"""Front end over an embedded CRuby: iseqw.to_a -> rawiseq objects."""

# Only this module and boot.py import rpython; the rest is CPython-safe.

from rpyyarv import boot
from rpyyarv import rawiseq
from rpyyarv import to_a_layout
from rpyyarv.error import LoadError
from rpyyarv.to_a_layout import (I_BODY, I_CATCH, I_LABEL, I_LOCALS, I_MAGIC, I_MISC,
                         I_PARAMS, I_TYPE)

EVENT_PREFIX = 'RUBY_EVENT_'

_MOVED = 'iseq_data_to_ary in iseq.c moved a field; update to_a_layout.py'

# params hash keys that are not parameters (iseq.c:3425-3462, 615).
PLAIN_PARAM_KEYS = ['lead_num', 'use_block', 'opt', 'rest_start',
                    'post_start', 'post_num', 'ambiguous_param0',
                    'block_start', 'keyword', 'kwbits', 'kwrest']

# Outside this the ISeq has real params, so arg_size isn't lead_num.
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
    me = len(program.iseqs)
    names, required, defaults = _keywords(pending, owners, params, me)
    raw.kw_names = names
    raw.kw_required = required
    raw.kw_defaults = defaults
    raw.kw_bits = _int_or(boot.hash_aref(params, 'kwbits'), -1)
    raw.kwrest = _int_or(boot.hash_aref(params, 'kwrest'), -1)
    raw.local_names = _local_names(boot.ary_entry(ary, I_LOCALS))
    if len(names) > 0 and raw.kw_bits < 0:
        raise LoadError("'%s' has keyword parameters but no kwbits slot: %s"
                        % (raw.name, _MOVED))
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
        elif boot.is_fixnum(e):
            # A bare Integer in the body is the source line that follows it.
            raw.set_line(boot.num2long(e))


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
        # The VALUE, not its bytes: rb_str_new would lose the encoding.
        return rawiseq.RawOperand(rawiseq.OP_VALUE, v, boot.str_of(v))
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
            kw_names = _kw_arg_names(v)
            return rawiseq.RawOperand(
                rawiseq.OP_CALL, boot.num2long(argc), name,
                _int_or(boot.hash_aref(v, 'flag'), 0),
                len(kw_names) > 0, None, kw_names)
    # Float, Range, Regexp and the rest cross as the VALUE itself.
    return rawiseq.RawOperand(rawiseq.OP_VALUE, v, boot.inspect(v))


def _catches(pending, owners, catch, me):
    """An entry's ISeq joins the same pending queue as nested ISeqs."""
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
    """iseq.c:3437 omits lead_num without has_lead; arg_size counts it."""
    if len(_param_keys(params, NO_PARAM_KEYS)) == 0:
        return _int_or(boot.hash_aref(misc, 'arg_size'), 0)
    return _int_or(boot.hash_aref(params, 'lead_num'), 0)


def _opt_labels(params):
    """Entry i starts the body with i optionals filled (vm_args.c:906)."""
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


def _keywords(pending, owners, params, me):
    """iseq.c:3442: bare Symbol required, [name] computed, [n, v] static."""
    v = boot.hash_aref(params, 'keyword')
    if boot.is_nil(v):
        return [], 0, []
    if not boot.is_array(v):
        raise LoadError('the keyword parameter list is not an Array: %s'
                        % _MOVED)
    names = []
    defaults = []
    required = 0
    optional_seen = False
    n = boot.ary_len(v)
    i = 0
    while i < n:
        e = boot.ary_entry(v, i)
        i += 1
        if boot.is_symbol(e):
            if optional_seen:
                raise LoadError('a required keyword follows an optional one: '
                                '%s' % _MOVED)
            names.append(boot.sym_of(e))
            defaults.append(None)
            required += 1
            continue
        if not boot.is_array(e) or boot.ary_len(e) < 1 or \
                boot.ary_len(e) > 2 or not boot.is_symbol(boot.ary_entry(e, 0)):
            raise LoadError('a keyword parameter entry is neither a Symbol '
                            'nor a 1-or-2 element Array: %s' % _MOVED)
        optional_seen = True
        names.append(boot.sym_of(boot.ary_entry(e, 0)))
        if boot.ary_len(e) == 2:
            defaults.append(_operand(pending, owners, boot.ary_entry(e, 1),
                                     me))
        else:
            defaults.append(None)
    return names, required, defaults


def _kw_arg_names(v):
    """The call site's keyword names (iseq.c:3532), one per value."""
    kw = boot.hash_aref(v, 'kw_arg')
    if boot.is_nil(kw):
        return []
    if not boot.is_array(kw) or boot.ary_len(kw) == 0:
        raise LoadError('a call site has a kw_arg that is not a non-empty '
                        'Array: %s' % _MOVED)
    names = []
    n = boot.ary_len(kw)
    i = 0
    while i < n:
        e = boot.ary_entry(kw, i)
        if not boot.is_symbol(e):
            raise LoadError('a call site keyword is not a Symbol: %s' % _MOVED)
        names.append(boot.sym_of(e))
        i += 1
    return names


def _local_names(ary):
    """One name per slot in local_slot's order; a hidden slot stays ''."""
    out = []
    n = boot.ary_len(ary)
    i = 0
    while i < n:
        v = boot.ary_entry(ary, i)
        out.append(boot.sym_of(v) if boot.is_symbol(v) else '')
        i += 1
    return out


def _int_or(v, default):
    if boot.is_nil(v):
        return default
    return boot.num2long(v)


def _extra_params(params):
    """The parameter kinds RPyYARV cannot place."""
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
