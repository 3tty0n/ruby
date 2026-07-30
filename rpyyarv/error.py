class RPyYarvError(Exception):
    pass


class UnsupportedOperation(RPyYarvError):
    def __init__(self, msg):
        self.msg = msg


class LoadError(RPyYarvError):
    # Malformed input, kept apart from UnsupportedOperation so the count of
    # unimplemented instructions stays a count of real work.
    def __init__(self, msg):
        self.msg = msg
