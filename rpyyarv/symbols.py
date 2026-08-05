"""Interned names: an ID is an index into this table, as in CRuby."""

_ids = {}
# Keyed by ID rather than a list: len() of a prebuilt list folds to its
# translation-time length, so appends made at run time went unseen.
_names = {}


def intern(name):
    if name in _ids:
        return _ids[name]
    mid = len(_ids)
    _ids[name] = mid
    _names[mid] = name
    return mid


def name_of(mid):
    if mid in _names:
        return _names[mid]
    return '<id %d>' % mid
