"""Interned names: an ID is an index into this table, as in CRuby."""

_ids = {}
# A dict, not a list: len() of a prebuilt list folds at translation time.
_names = {}


class _Next(object):
    # Likewise: len(_ids) would fold and run-time IDs would alias.
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
