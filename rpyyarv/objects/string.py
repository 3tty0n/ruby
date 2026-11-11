import math
import sys

from rpyyarv import symbols
from rpyyarv.methods import W_CFunc
from rpyyarv.objects.array import W_Array, num2long
from rpyyarv.objects.base import W_Root
from rpyyarv.objects.float import W_Float
from rpyyarv.objects.klass import w_string_class
from rpyyarv.objects.regexp import W_Regexp
from rpyyarv.objects.transparent import (W_Integer, describe_conversion,
                                         newbool, newint, w_nil)
from rpyyarv.error import UnsupportedOperation
from rpyyarv.rlib import StringBuilder, float_fixed

ENC_UTF8 = 0
ENC_BINARY = 1
ENC_NAMES = ['UTF-8', 'BINARY (ASCII-8BIT)']

class W_String(W_Root):
    # While builder holds what << appended, strval is stale: read str_w()
    def __init__(self, strval, encoding=ENC_UTF8, frozen=False):
        self.strval = strval
        self.encoding = encoding
        self.frozen = frozen
        self.builder = None

    def getclass(self):
        return w_string_class

    def str_w(self):
        if self.builder is not None:
            self.strval = self.builder.build()
            self.builder = None
        return self.strval

    def to_s_str(self):
        return self.str_w()

    def repr(self):
        return '"%s"' % self.str_w()

    def copy(self):
        return W_String(self.str_w(), self.encoding)

    def append(self, s):
        if self.builder is None:
            self.builder = StringBuilder()
            self.builder.append(self.strval)
        self.builder.append(s)


def is_ascii(s):
    for c in s:
        if ord(c) >= 0x80:
            return False
    return True


def _incompatible(enc_a, enc_b):
    return UnsupportedOperation('incompatible character encodings: %s and %s'
                                % (ENC_NAMES[enc_a], ENC_NAMES[enc_b]))


def _compatible(w_a, w_b):
    """The encoding rb_enc_compatible gives w_a and w_b."""
    enc = w_a.encoding
    if w_b.encoding != enc and not is_ascii(w_b.str_w()):
        if not is_ascii(w_a.str_w()):
            raise _incompatible(enc, w_b.encoding)
        enc = w_b.encoding
    return enc


def concat2(w_a, w_b):
    return W_String(w_a.str_w() + w_b.str_w(), _compatible(w_a, w_b))


def concat(parts_w):
    """parts_w joined, as appending them one by one to an empty String."""
    enc = ENC_UTF8
    i = 0
    while i < len(parts_w):
        w_part = parts_w[i]
        if w_part.encoding != enc and not is_ascii(w_part.str_w()):
            j = 0
            while j < i:
                if not is_ascii(parts_w[j].str_w()):
                    raise _incompatible(enc, w_part.encoding)
                j += 1
            enc = w_part.encoding
        i += 1
    return W_String(''.join([w.str_w() for w in parts_w]), enc)


def str_eql(w_a, w_b):
    """rb_str_hash_cmp: the same bytes, in comparable encodings."""
    return w_a.str_w() == w_b.str_w() and (w_a.encoding == w_b.encoding
                                           or is_ascii(w_a.str_w()))


def char_count(s):
    n = 0
    i = 0
    while i < len(s):
        i += _char_width(s, i)
        n += 1
    return n


class W_StrAref(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        if len(args_w) != 1:
            raise UnsupportedOperation(
                '%s with %d arguments is not supported yet'
                % (symbols.name_of(self.mid), len(args_w)))
        w_index = args_w[0]
        if not isinstance(w_index, W_Integer):
            raise UnsupportedOperation('%s with %s is not supported yet'
                                       % (symbols.name_of(self.mid),
                                          w_index.getclass().name))
        s = w_recv.str_w()
        index = w_index.int_w()
        binary = w_recv.encoding == ENC_BINARY
        if index < 0:
            index += len(s) if binary else char_count(s)
            if index < 0:
                return w_nil
        if binary:
            if index >= len(s):
                return w_nil
            return W_String(s[index], ENC_BINARY)
        i = 0
        while i < len(s) and index > 0:
            i += _char_width(s, i)
            index -= 1
        if i >= len(s):
            return w_nil
        return W_String(s[i:i + _char_width(s, i)])


class W_StrEqual(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        w_other = args_w[0]
        return newbool(isinstance(w_other, W_String)
                       and str_eql(w_recv, w_other))


TO_STR = symbols.intern('to_str')


def _string_arg(name, w_other):
    if isinstance(w_other, W_String):
        return w_other
    if w_other.lookup_class().find_method(TO_STR) is not None:
        raise UnsupportedOperation(
            '%s with %s through to_str is not supported yet'
            % (name, w_other.getclass().name))
    raise UnsupportedOperation('no implicit conversion of %s into String'
                               % describe_conversion(w_other))


class W_StrPlus(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        return concat2(w_recv, _string_arg('+', args_w[0]))


class W_StrAppend(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        w_other = args_w[0]
        if not isinstance(w_other, W_Integer):
            w_other = _string_arg('<<', w_other)
        if w_recv.frozen:
            raise UnsupportedOperation("can't modify frozen String: %s"
                                       % w_recv.repr())
        if not isinstance(w_other, W_String):
            raise UnsupportedOperation('<< with an Integer is not supported yet')
        w_recv.encoding = _compatible(w_recv, w_other)
        w_recv.append(w_other.str_w())
        return w_recv


class W_Unpack(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        fmt = _string_arg('unpack', args_w[0]).str_w()
        if fmt != 'c*':
            raise UnsupportedOperation('unpack("%s") is not supported yet'
                                       % fmt)
        if w_block is not None:
            raise UnsupportedOperation('unpack with a block is not supported '
                                       'yet')
        items_w = []
        for c in w_recv.str_w():
            n = ord(c)
            if n >= 0x80:
                n -= 0x100
            items_w.append(newint(n))
        return W_Array(items_w)


class W_StrTimes(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        n = num2long(args_w[0])
        if n < 0:
            raise UnsupportedOperation('negative argument')
        if n > 0 and len(w_recv.str_w()) > _MAX_FIXNUM // n:
            raise UnsupportedOperation('argument too big')
        return W_String(w_recv.str_w() * n, w_recv.encoding)


def _fixed_precision(fmt):
    i = 1
    if i < len(fmt) and fmt[i] == '0':
        i += 1
    if not fmt.startswith('%') or i >= len(fmt) or fmt[i] != '.':
        return -1
    start = i + 1
    end = start
    while end < len(fmt) and fmt[end].isdigit():
        end += 1
    if end != len(fmt) - 1 or fmt[end] != 'f' or end - start > 3:
        return -1
    if end == start:
        return 0
    return int(fmt[start:end])


class W_StrFormat(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        fmt = w_recv.str_w()
        precision = _fixed_precision(fmt)
        if precision < 0:
            raise UnsupportedOperation('format %s is not supported yet' % fmt)
        w_arg = args_w[0]
        if not isinstance(w_arg, W_Float):
            raise UnsupportedOperation('format %s of %s is not supported yet'
                                       % (fmt, w_arg.getclass().name))
        x = w_arg.floatval
        if math.isnan(x):
            return W_String('NaN')
        if math.isinf(x):
            if x > 0.0:
                return W_String('Inf')
            return W_String('-Inf')
        return W_String(float_fixed(x, precision))


class W_Length(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        if w_recv.encoding == ENC_BINARY:
            return newint(len(w_recv.str_w()))
        return newint(char_count(w_recv.str_w()))

_MAX_FIXNUM = sys.maxsize


def _is_digit(c):
    return '0' <= c <= '9'


def string_to_i(s):
    n = len(s)
    i = 0
    while i < n and s[i] in ' \t\n\v\f\r':
        i += 1
    sign = 1
    if i < n and (s[i] == '+' or s[i] == '-'):
        if s[i] == '-':
            sign = -1
        i += 1
    if i + 1 < n and s[i] == '0' and (s[i + 1] == 'd' or s[i + 1] == 'D'):
        i += 2
    start = i
    value = 0
    while i < n:
        c = s[i]
        if _is_digit(c):
            digit = ord(c) - ord('0')
            if value > (_MAX_FIXNUM - digit) // 10:
                raise UnsupportedOperation(
                    "to_i on %s: the result does not fit in a Fixnum" % s)
            value = value * 10 + digit
        elif not (c == '_' and i > start and _is_digit(s[i - 1])
                  and i + 1 < n and _is_digit(s[i + 1])):
            break
        i += 1
    return sign * value


class W_ToI(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        return newint(string_to_i(w_recv.str_w()))

def _char_width(s, i):
    """Bytes in the UTF-8 character at s[i]; a broken one is a byte on its
    own, as String#each_char treats it.

    shortcut: CRuby's split(//) raises ArgumentError on a broken string, this
    splits it anyway; upgrade when exceptions exist.
    """
    c = ord(s[i])
    if c < 0xC2 or c > 0xF4:
        return 1
    if c < 0xE0:
        width = 2
    elif c < 0xF0:
        width = 3
    else:
        width = 4
    if i + width > len(s):
        return 1
    lo = 0x80
    hi = 0xBF
    if c == 0xE0:
        lo = 0xA0
    elif c == 0xED:
        hi = 0x9F
    elif c == 0xF0:
        lo = 0x90
    elif c == 0xF4:
        hi = 0x8F
    for k in range(1, width):
        b = ord(s[i + k])
        if b < lo or b > hi:
            return 1
        lo = 0x80
        hi = 0xBF
    return width


def _utf8_chars(s):
    chars_w = []
    i = 0
    while i < len(s):
        width = _char_width(s, i)
        chars_w.append(W_String(s[i:i + width]))
        i += width
    return chars_w


class W_Split(W_CFunc):
    def call(self, w_recv, args_w, w_block):
        assert isinstance(w_recv, W_String)
        w_pattern = args_w[0]
        if w_recv.encoding == ENC_BINARY:
            raise UnsupportedOperation(
                'split on a BINARY String is not supported yet')
        if isinstance(w_pattern, W_Regexp) and w_pattern.pattern == '':
            s = w_recv.str_w()
            n = len(s)
            chars_w = []
            i = 0
            while i < n:
                c = s[i]
                if c < '\x80':
                    size = 1
                elif '\xc2' <= c <= '\xdf':
                    size = 2
                elif '\xe0' <= c <= '\xef':
                    size = 3
                elif '\xf0' <= c <= '\xf4':
                    size = 4
                else:
                    size = 0
                valid = size > 0 and i + size <= n
                j = i + 1
                while valid and j < i + size:
                    valid = '\x80' <= s[j] <= '\xbf'
                    j += 1
                if valid and size > 2:
                    second = s[i + 1]
                    valid = not ((c == '\xe0' and second < '\xa0')
                                 or (c == '\xed' and second > '\x9f')
                                 or (c == '\xf0' and second < '\x90')
                                 or (c == '\xf4' and second > '\x8f'))
                if not valid:
                    raise UnsupportedOperation(
                        "split on %s: invalid byte sequence in UTF-8"
                        % w_recv.repr())
                chars_w.append(W_String(s[i:i + size]))
                i += size
            return W_Array(chars_w)
        raise UnsupportedOperation(
            "split on %s: RPyYARV only supports split(//) so far"
            % w_pattern.repr())

def install(w_class):
    mid = symbols.intern('to_i')
    w_class.add_method(mid, W_ToI(mid, 0))  # arity=0
    split_id = symbols.intern('split')
    w_class.add_method(split_id, W_Split(split_id, 1))  # arity=1: 0 arguments and 2 arguments(with limit) are not supported yet
    for name in ['length', 'size']:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_Length(mid, 0))
    for name in ['==', '===']:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_StrEqual(mid, 1))
    for name in ['[]', 'slice']:
        mid = symbols.intern(name)
        w_class.add_method(mid, W_StrAref(mid, -1))
    plus_id = symbols.intern('+')
    w_class.add_method(plus_id, W_StrPlus(plus_id, 1))
    append_id = symbols.intern('<<')
    w_class.add_method(append_id, W_StrAppend(append_id, 1))
    unpack_id = symbols.intern('unpack')
    w_class.add_method(unpack_id, W_Unpack(unpack_id, 1))
    times_id = symbols.intern('*')
    w_class.add_method(times_id, W_StrTimes(times_id, 1))
    format_id = symbols.intern('%')
    w_class.add_method(format_id, W_StrFormat(format_id, 1))
