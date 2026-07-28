class RPyYarvError(Exception):
    pass


class UnsupportedOperation(RPyYarvError):
    def __init__(self, msg):
        self.msg = msg
