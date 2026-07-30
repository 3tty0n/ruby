"""Interned names: an ID is an index into this table, as in CRuby.

Only the loader interns, so these tables are written before the interpreter
runs and read-only afterwards.
"""

_ids = {}
_names = []


def intern(name):
    if name in _ids:
        return _ids[name]
    mid = len(_names)
    _names.append(name)
    _ids[name] = mid
    return mid


def name_of(mid):
    if mid < 0 or mid >= len(_names):
        return '<id %d>' % mid
    return _names[mid]
