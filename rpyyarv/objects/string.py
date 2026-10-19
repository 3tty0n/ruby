import sys

import symbols
from methods import W_CFunc
from objects.array import W_Array
from objects.base import W_Root
from objects.klass import w_string_class
from objects.regexp import W_Regexp
from objects.transparent import newint
from error import UnsupportedOperation

class W_String(W_Root):
    # Immutable: nothing mutates a string yet, so frozen, chilled and
    # ordinary literals are all the same object here.
    def __init__(self, strval):
        self.strval = strval

    def getclass(self):
        return w_string_class

    def str_w(self):
        return self.strval

    def to_s_str(self):
        return self.strval

    def repr(self):
        return '"%s"' % self.strval

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
        try:
            return newint(int(w_recv.strval))
        except ValueError:
            raise UnsupportedOperation(
                "to_i on %s: RPyYARV only supports a plain integer string, "
                "not Ruby's full parsing" % w_recv.repr())

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
        if isinstance(w_pattern, W_Regexp) and w_pattern.pattern == '':
            s = w_recv.strval
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
