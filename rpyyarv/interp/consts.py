"""Constants, class variables and defined?."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import helpers
from rpyyarv import optable
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.error import UnsupportedOperation
from rpyyarv.frame import Frame
from rpyyarv.rlib import dont_look_inside, promote

from rpyyarv.interp.consts_ids import EQQ, NEW, ROOT_CBASE
from rpyyarv.interp.cref import _cref_klass, _cref_of, _push_cref

DEFINED_IVAR = 2


DEFINED_GVAR = 4


DEFINED_CVAR = 5


DEFINED_CONST = 6


DEFINED_METHOD = 7


DEFINED_YIELD = 8


DEFINED_FUNC = 16


DEFINED_CONST_FROM = 17


def _const_path(frame, iseq, idx):
    """A per-site memo of _const_walk; the global cache is the fallback."""
    # Keyed on the innermost class: _push_cref interns one node per pair.
    base = _const_base(frame)
    entry = dispatch.const_site(iseq.path_sites[idx], dispatch.consts.version)
    if entry is not None and entry.base == base:
        return entry.value
    return _const_path_miss(iseq.path_sites[idx], base, _cref_of(frame),
                            iseq.paths[idx])


@dont_look_inside
def _const_path_miss(site, base, cref, path):
    v = _const_walk(cref, path)
    dispatch.const_site_fill(site, base, v)
    return v


def _const_walk(cref, path):
    """vm_get_ev_const_chain; a leading empty segment is `::Foo`."""
    # An id compare, not a name lookup: the dict read would stay in the trace.
    if path[0] == ROOT_CBASE:
        base = value.core_class(value.C_OBJECT)
    else:
        base = _const_lexical(cref, path[0])
    i = 1
    while i < len(path):
        base = dispatch.const_get_from(base, path[i])
        i += 1
    return base


def _const_lexical(cref, mid):
    """vm_get_ev_const, nil cbase: lexical tables, then ancestors and Object."""
    node = cref
    # The outermost entry is toplevel Object; only the walk below covers it.
    while node.outer is not None:
        if not node.by_eval:
            v = dispatch.const_at(node.klass, mid)
            if v != value.Q_UNDEF:
                return v
        node = node.outer
    return dispatch.const_get(_cref_klass(cref), mid)


def _run_once(frame, iseq, idx):
    """A `once` body, in a frame chained to this one; result cached."""
    body = iseq.iseqs[idx]
    callee = Frame(body, frame.self_val, _cref_of(frame), frame.entry)
    callee.defining_frame = frame
    v = execute(body, callee)
    iseq.once_cache[idx] = v
    return v


@dont_look_inside
def _cvar_base(cref):
    """vm_get_cvar_base: innermost lexical scope that is a real class."""
    node = cref
    while node is not None:
        if node.klass != 0 and not node.by_eval \
                and not boot.is_singleton_class(node.klass):
            return node.klass
        if node.outer is None:
            break
        node = node.outer
    return value.core_class(value.C_OBJECT)


@dont_look_inside
def _cvar_get(cref, mid):
    return boot.cvar_get(_cvar_base(cref), rubycall.rid(mid))


@dont_look_inside
def _cvar_set(cref, mid, v):
    boot.cvar_set(_cvar_base(cref), rubycall.rid(mid), v)


def _cbase(frame):
    """vm_get_cbase: innermost cref klass, an eval-pushed one included."""
    node = frame.cref
    if node is not None and node.klass != 0:
        return node.klass
    return _const_base(frame)


def _const_base(frame):
    """The cbase a `class Foo::Bar` or a setconstant resolves against."""
    node = frame.cref
    if node is not None and node.const_base != 0:
        return node.const_base
    entry = frame.entry
    if entry is not None and entry.cref != 0:
        return entry.cref
    return value.core_class(value.C_OBJECT)


def _defined_const(cref, rid):
    node = cref
    while node.outer is not None:
        if boot.const_defined(node.klass, rid, 0):
            return True
        node = node.outer
    return boot.const_defined(_cref_klass(cref), rid, 1)


def _defined(frame, kind, obj, recv):
    mid = _name_mid(obj)
    if mid == rubycall.NO_MID:
        return False
    rid = rubycall.rid(mid)
    if kind == DEFINED_IVAR:
        return boot.ivar_defined(frame.self_val, rid)
    if kind == DEFINED_CVAR:
        return boot.cvar_defined(_cvar_base(_cref_of(frame)), rid)
    if kind == DEFINED_CONST:
        return _defined_const(_cref_of(frame), rid)
    if kind == DEFINED_CONST_FROM:
        return recv != value.Q_NIL and boot.const_defined(recv, rid, 1)
    if kind == DEFINED_FUNC:
        return boot.method_defined(recv, rid, 1)
    if kind == DEFINED_METHOD:
        return boot.method_defined(recv, rid, 0)
    if kind == DEFINED_YIELD:
        return frame.block is not None
    raise UnsupportedOperation('defined? type %d is not implemented' % kind)


def _defineclass(frame, mid, w_body, cbase, super_v, is_module=False):
    if is_module:
        klass = dispatch.define_module(cbase, mid)
    else:
        klass = dispatch.define_class(cbase, mid, super_v)
    body = Frame(w_body, klass, _push_cref(_cref_of(frame), klass))
    ret = execute(w_body, body)
    # Reopening a class is where CRuby-side operator redefinitions show up.
    helpers.refresh()
    return ret


def _definesingletonclass(frame, w_body, obj):
    klass = boot.singleton_class(obj)
    body = Frame(w_body, klass, _push_cref(_cref_of(frame), klass))
    ret = execute(w_body, body)
    helpers.refresh()
    return ret


def _opt_new_alloc(klass):
    """A fresh instance, or 0; only RPyYARV's classes kept Class#new."""
    # Promoted: both tests fold, leaving only the allocation in the trace.
    klass = promote(klass)
    if not dispatch.is_known_class(klass):
        return 0
    if helpers.ary_new_pristine(klass):
        # The miss branch's `send new` is where _array_new runs.
        return 0
    # A `def self.new` (liquid-c's ResourceLimits) must win over the alloc.
    if dispatch.owner_of(promote(value.class_of(klass)), NEW) != \
            value.core_class(value.C_CLASS):
        return 0
    return dispatch.alloc(klass)


@dont_look_inside
def _checkmatch(target, pattern, flag):
    """vm_check_match, vm_insnhelper.c:5772."""
    if flag & optable.CHECKMATCH_ARRAY:
        if value.is_immediate(pattern) or not boot.is_array(pattern):
            raise UnsupportedOperation(
                'checkmatch with an array flag needs an Array of patterns')
        n = boot.ary_len(pattern)
        i = 0
        while i < n:
            if _match_one(target, boot.ary_entry(pattern, i), flag):
                return value.Q_TRUE
            i += 1
        return value.Q_FALSE
    return value.newbool(_match_one(target, pattern, flag))


def _match_one(target, pattern, flag):
    kind = flag & optable.CHECKMATCH_TYPE_MASK
    if kind == optable.CHECKMATCH_TYPE_WHEN:
        return value.is_true(pattern)
    is_module = not value.is_immediate(pattern) and boot.is_class(pattern)
    if kind == optable.CHECKMATCH_TYPE_RESCUE and not is_module:
        raise UnsupportedOperation('class or module required for rescue clause')
    if is_module:
        # TODO: a subclass redefining #=== is ignored, as in vm_opt_*.
        return boot.obj_is_kind_of(target, pattern)
    return value.is_true(rubycall.call1(pattern, EQQ, target))


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.sends import _name_mid
from rpyyarv.interp.execute import execute
