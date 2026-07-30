from objects.base import W_Root


class W_Array(W_Root):
    # Only literal arrays exist so far, and nothing mutates them.
    def __init__(self, items_w):
        self.items_w = items_w

    def repr(self):
        return '<W_Array %d>' % len(self.items_w)
