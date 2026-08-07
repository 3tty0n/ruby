class RPyYarvError(Exception):
    def __init__(self, msg):
        self.msg = msg


class UnsupportedOperation(RPyYarvError):
    pass


class RubyException(Exception):
    """A Ruby exception in flight, carrying the exception object itself.

    Kept apart from RPyYarvError: this one is Ruby's to catch. The VALUE is
    reachable for CRuby's GC through whichever catch frame or gcroots slot
    holds it while the unwinding runs.
    """
    def __init__(self, value, name):
        self.value = value
        # The call that raised, for the message when nothing rescues it.
        self.name = name


class LoadError(RPyYarvError):
    # Malformed input, kept apart from UnsupportedOperation so the count of
    # unimplemented instructions stays a count of real work.
    pass
