"""Interned names: an ID is an index into this table, as in CRuby."""

_ids = {}
# A dict, not a list: len() of a prebuilt container folds to its
# translation-time size, so run-time appends went unseen.
_names = {}


class _Next(object):
    # Likewise: len(_ids) would fold, and every run-time ID would alias one
    # interned at import time.
    def __init__(self):
        self.mid = 0


_next = _Next()


def intern(name):
    if name in _ids:
        return _ids[name]
    mid = _next.mid
    _next.mid = mid + 1
    _ids[name] = mid
    _names[mid] = name
    return mid


def name_of(mid):
    if mid in _names:
        return _names[mid]
    return '<id %d>' % mid
