"""Read scripts/dump_iseq.rb's text dump into rawiseq objects; grammar there."""

from rpyyarv import rawiseq
from rpyyarv.error import LoadError

FORMAT_VERSION = 1

_SEP = '\t'


def _int(field, what):
    try:
        return int(field)
    except ValueError:
        raise LoadError('%s is not a number: %s' % (what, field))


def _unescape(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\' and i + 1 < n:
            e = text[i + 1]
            if e == 't':
                out.append('\t')
            elif e == 'n':
                out.append('\n')
            elif e == 'r':
                out.append('\r')
            elif e == '\\':
                out.append('\\')
            else:
                raise LoadError('unknown escape \\%s in %s' % (e, text))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _split_items(body):
    items = []
    cur = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == '\\' and i + 1 < n:
            e = body[i + 1]
            if e == 'c':
                cur.append(',')
            elif e == '\\':
                cur.append('\\')
            else:
                cur.append(c)
                cur.append(e)
            i += 2
        elif c == ',':
            items.append(''.join(cur))
            cur = []
            i += 1
        else:
            cur.append(c)
            i += 1
    if len(cur) > 0 or len(items) > 0:
        items.append(''.join(cur))
    return items


def _operand(token):
    if len(token) < 2 or token[1] != ':':
        raise LoadError('malformed operand: %s' % token)
    kind = token[0]
    body = token[2:]
    if kind == 'i':
        return rawiseq.int_operand(_int(body, 'operand'))
    if kind == 'n':
        return rawiseq.RawOperand(rawiseq.OP_NIL)
    if kind == 't':
        return rawiseq.RawOperand(rawiseq.OP_TRUE)
    if kind == 'f':
        return rawiseq.RawOperand(rawiseq.OP_FALSE)
    if kind == 'y':
        return rawiseq.RawOperand(rawiseq.OP_SYM, 0, _unescape(body))
    if kind == 's':
        return rawiseq.RawOperand(rawiseq.OP_STR, 0, _unescape(body))
    if kind == 'q':
        return rawiseq.RawOperand(rawiseq.OP_ISEQ, _int(body, 'iseq index'))
    if kind == 'a':
        items = []
        for item in _split_items(body):
            items.append(_operand(item))
        return rawiseq.RawOperand(rawiseq.OP_ARRAY, 0, '', 0, False, items)
    if kind == 'x':
        return rawiseq.RawOperand(rawiseq.OP_OTHER, 0, _unescape(body))
    if kind == 'c':
        parts = body.split(',', 3)
        if len(parts) != 4:
            raise LoadError('malformed call data: %s' % token)
        return rawiseq.RawOperand(rawiseq.OP_CALL,
                                  _int(parts[0], 'orig_argc'),
                                  _unescape(parts[3]),
                                  _int(parts[1], 'call flags'),
                                  _int(parts[2], 'kw_arg') != 0)
    raise LoadError('unknown operand kind %s in %s' % (kind, token))


def _field(fields, i, what):
    if i >= len(fields):
        raise LoadError('record is missing its %s: %s' % (what, fields[0]))
    return fields[i]


def parse(text):
    program = None
    raw = None
    lead_num = 0
    extra_params = ''
    nlocals = -1
    stack_max = -1
    catch_types = []
    pending = None
    lineno = 0

    for line in text.split('\n'):
        lineno += 1
        if len(line) == 0 or line[0] == '#':
            continue
        fields = line.split(_SEP)
        kind = fields[0]

        if kind == 'dump':
            version = _int(_field(fields, 1, 'format version'), 'version')
            if version != FORMAT_VERSION:
                raise LoadError('dump format version %d, expected %d'
                                % (version, FORMAT_VERSION))
            program = rawiseq.RawProgram(_field(fields, 2, 'ruby version'),
                                         _field(fields, 3, 'path'))
            continue

        if program is None:
            raise LoadError('line %d: no dump header' % lineno)

        if kind == 'iseq':
            index = _int(_field(fields, 1, 'index'), 'iseq index')
            if index != len(program.iseqs):
                raise LoadError('iseq %d is out of order (expected %d)'
                                % (index, len(program.iseqs)))
            pending = fields
            nlocals = -1
            stack_max = -1
            lead_num = 0
            extra_params = ''
            catch_types = []
            raw = None
        elif kind == 'locals':
            nlocals = _int(_field(fields, 1, 'local count'), 'locals')
        elif kind == 'stackmax':
            stack_max = _int(_field(fields, 1, 'stack size'), 'stackmax')
        elif kind == 'params':
            lead_num = _int(_field(fields, 1, 'lead_num'), 'lead_num')
            extra_params = fields[2] if len(fields) > 2 else ''
        elif kind == 'catch':
            catch_types = []
            for _ in range(_int(_field(fields, 1, 'catch table size'),
                                'catch')):
                # Dump gives only counts; a label-less entry the loader refuses.
                catch_types.append(rawiseq.RawCatch('?'))
            if pending is None or nlocals < 0 or stack_max < 0:
                raise LoadError('line %d: incomplete iseq header' % lineno)
            raw = rawiseq.RawISeq(_field(pending, 3, 'label'),
                                  _field(pending, 2, 'type'),
                                  nlocals, stack_max, lead_num,
                                  extra_params, catch_types)
            program.add_iseq(raw)
            pending = None
        elif kind == 'insn':
            if raw is None:
                raise LoadError('line %d: instruction outside an iseq'
                                % lineno)
            operands = []
            for i in range(2, len(fields)):
                operands.append(_operand(fields[i]))
            raw.add_insn(rawiseq.RawInsn(_field(fields, 1, 'name'),
                                         operands))
        elif kind == 'label':
            if raw is None:
                raise LoadError('line %d: label outside an iseq' % lineno)
            raw.add_label(_field(fields, 1, 'label name'))
        elif kind == 'line' or kind == 'event':
            pass
        elif kind == 'endiseq':
            raw = None
        else:
            raise LoadError('line %d: unknown record %s' % (lineno, kind))

    if program is None:
        raise LoadError('empty dump')
    if len(program.iseqs) == 0:
        raise LoadError('dump contains no iseq')
    return program
