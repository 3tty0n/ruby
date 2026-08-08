class RPyYarvError(Exception):
    def __init__(self, msg):
        self.msg = msg


class UnsupportedOperation(RPyYarvError):
    pass


class RubyException(Exception):
    """A Ruby exception in flight; apart from RPyYarvError because this one is Ruby's to catch."""
    def __init__(self, value, name):
        # Marked through the catch frame or gcroots slot holding it while the
        # unwinding runs.
        self.value = value
        # The call that raised, for the message when nothing rescues it.
        self.name = name


class LoadError(RPyYarvError):
    # Kept apart from UnsupportedOperation so the count of unimplemented instructions stays a count of real work.
    pass
