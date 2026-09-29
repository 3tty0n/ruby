"""Interned names: an ID is an index into this table, as in CRuby."""

_ids = {}
# Keyed by ID rather than a list: len() of a prebuilt list folds to its
# translation-time length, so appends made at run time went unseen.
_names = {}


class _Counter(object):
    def __init__(self):
        self.value = 0


_next_id = _Counter()


def intern(name):
    if name in _ids:
        return _ids[name]
    mid = _next_id.value
    _next_id.value = mid + 1
    _ids[name] = mid
    _names[mid] = name
    return mid


def name_of(mid):
    if mid in _names:
        return _names[mid]
    return '<id %d>' % mid