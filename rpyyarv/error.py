class RPyYarvError(Exception):
    def __init__(self, msg):
        self.msg = msg


class UnsupportedOperation(RPyYarvError):
    pass


class RubyException(Exception):
    """A Ruby exception in flight; apart from RPyYarvError, Ruby catches it."""
    def __init__(self, value, name):
        # Marked through the catch frame or gcroots slot while unwinding.
        self.value = value
        # The call that raised, for the message when nothing rescues it.
        self.name = name


class LoadError(RPyYarvError):
    # Apart from UnsupportedOperation: that count is unimplemented insns only.
    pass


class _Errinfo(object):
    def __init__(self):
        # $! of each rescue body still running, innermost last.
        self.stack = []


errinfos = _Errinfo()
