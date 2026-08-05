try:
    from rpython.rlib.jit import JitDriver, elidable, promote
except ImportError:
    class JitDriver(object):
        def __init__(self, **kwargs):
            pass

        def jit_merge_point(self, **kwargs):
            pass

        def can_enter_jit(self, **kwargs):
            pass

    def elidable(func):
        return func

    def promote(x):
        return x
