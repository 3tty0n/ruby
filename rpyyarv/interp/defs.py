"""Method definition and visibility."""
from __future__ import absolute_import

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import helpers
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import UnsupportedOperation
from rpyyarv.rlib import dont_look_inside, raw_word, unroll_safe

from rpyyarv.interp.consts_ids import ALIAS_METHOD, NEW, PROTECTED, ATTR_READER, ATTR_WRITER, CORE_ALIAS, CORE_UNDEF, INSTANCE_EXEC, MODULE_FUNCTION, PRIVATE, PRIVATE_CLASS_METHOD, UNDEF_METHOD
from rpyyarv.interp.cref import _cref_of, _push_cref
from rpyyarv.interp.args import NO_KEYWORDS

def define_method(frame, mid, w_iseq):
    """A def in a class body lands on it; a toplevel def is private."""
    node = frame.cref
    if node is None:
        dispatch.define(value.core_class(value.C_OBJECT), mid, w_iseq, True,
                        0, _cref_of(frame))
    elif frame.module_func:
        dispatch.define(node.klass, mid, w_iseq, True, node.klass, node)
        dispatch.define_singleton(node.klass, mid, w_iseq, node.klass, node)
    else:
        dispatch.define(node.klass, mid, w_iseq, frame.private_pragma,
                        node.klass, node, 0, 0, frame.protected_pragma)


@unroll_safe
def _define_attrs(frame, mid, klass, recv_at, argc):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    # First, so a name CRuby rejects raises before anything is registered.
    ret = rubycall.call(klass, mid, args)
    private = frame.private_pragma
    if private:
        # CRuby's send never learns RPyYARV's private pragma: make them private.
        names = _attr_method_names(mid, args)
        if len(names) > 0:
            rubycall.call(klass, PRIVATE, names)
    _install_attrs(klass, mid, args, private)
    return ret


def _attr_method_names(mid, args):
    names = []
    for i in range(len(args)):
        name = _attr_name(args[i])
        if name == '':
            continue
        if mid != ATTR_WRITER:
            names.append(rubycall.sym_value(symbols.intern(name)))
        if mid != ATTR_READER:
            names.append(rubycall.sym_value(symbols.intern(name + '=')))
    return names


@dont_look_inside
def _install_attrs(klass, mid, args, private=False):
    """attr_* still runs in CRuby; the registry gains native entries too."""
    for i in range(len(args)):
        name = _attr_name(args[i])
        if name == '':
            continue
        ivar = symbols.intern('@' + name)
        if mid != ATTR_WRITER:
            dispatch.define_attr(klass, symbols.intern(name), ivar,
                                 dispatch.KIND_ATTR_READER, private)
        if mid != ATTR_READER:
            dispatch.define_attr(klass, symbols.intern(name + '='), ivar,
                                 dispatch.KIND_ATTR_WRITER, private)


def _attr_name(v):
    if boot.is_symbol(v):
        return boot.sym_of(v)
    if not value.is_immediate(v) and boot.is_string(v):
        return boot.str_of(v)
    return ''


def _is_class_or_module(v):
    if value.is_immediate(v):
        return False
    kind = raw_word(v, value.FLAGS_WORD) & value.T_MASK
    return kind == value.T_CLASS or kind == value.T_MODULE


@unroll_safe
def _define_bmethod(frame, mid, recv, recv_at, w_block, private_pragma=False):
    """define_method: CRuby installs the real bmethod, plus a fast entry."""
    name_v = frame.stack[recv_at + 1]
    _drop(frame, recv_at)
    # First, so a name or block CRuby rejects raises before registering.
    ret = _call_with_block(recv, mid, [name_v], w_block)
    # A Symbol is a CRuby immediate: no is_immediate guard needed.
    if not boot.is_symbol(ret):
        return ret
    returned_mid = symbols.intern(boot.sym_of(ret))
    # recv is the class for `class C; define_method`, its class at toplevel.
    search = recv if _is_class_or_module(recv) else value.class_of(recv)
    if value.is_immediate(search):
        return ret
    owner = dispatch.owner_of(search, returned_mid)
    if value.is_immediate(owner) or owner == value.Q_NIL:
        return ret
    if private_pragma:
        # CRuby's send never learns RPyYARV's private pragma: make it private.
        rubycall.call(owner, PRIVATE, [ret])
    # is_lambda is quasi-immutable: flag once here, never mutate later.
    lambda_block = block_mod.W_Block(w_block.w_iseq, w_block.frame,
                                     w_block.outer, is_lambda=True)
    dispatch.define_bmethod(owner, returned_mid, lambda_block,
                            frame.cref is None or private_pragma)
    return ret


@unroll_safe
def _define_bmethod_modfunc(frame, mid, recv, recv_at, w_block):
    """define_method under module_function: private plus a singleton copy."""
    name_v = frame.stack[recv_at + 1]
    _drop(frame, recv_at)
    ret = _call_with_block(recv, mid, [name_v], w_block)
    if not boot.is_symbol(ret):
        return ret
    rubycall.call(recv, MODULE_FUNCTION, [ret])
    returned_mid = symbols.intern(boot.sym_of(ret))
    lambda_block = block_mod.W_Block(w_block.w_iseq, w_block.frame,
                                     w_block.outer, is_lambda=True)
    dispatch.define_bmethod(recv, returned_mid, lambda_block, True)
    dispatch.define_singleton_bmethod(recv, returned_mid, lambda_block)
    return ret


@dont_look_inside
def _singleton_of(recv):
    """The singleton class instance_eval pushes as cref; 0 when it has none."""
    if value.is_immediate(recv):
        return 0
    return boot.singleton_class(recv)


@unroll_safe
def _instance_eval(frame, mid, recv, recv_at, argc, w_block):
    """instance_eval/exec: self rebound here; CRuby keeps the written self."""
    args = []
    if mid == INSTANCE_EXEC:
        i = 0
        while i < argc:
            args.append(frame.stack[recv_at + 1 + i])
            i += 1
    else:
        args.append(recv)
    sing = _singleton_of(recv)
    cref = None
    if sing != 0:
        # Over the block's own chain (yield_under), never the caller's.
        cref = _push_cref(_cref_of(w_block.frame), sing, True)
    _drop(frame, recv_at)
    return call_block(w_block, args, NO_KEYWORDS, False, recv, cref)


@unroll_safe
def _module_eval_block(frame, recv, recv_at, w_block):
    """class_eval/module_eval block: CRuby would keep the written cref."""
    args = [recv]
    # Over the block's own chain (yield_under), never the caller's.
    cref = _push_cref(_cref_of(w_block.frame), recv, True)
    _drop(frame, recv_at)
    return call_block(w_block, args, NO_KEYWORDS, False, recv, cref)


@unroll_safe
def _class_new_block(frame, recv, recv_at, argc, w_block, mid=NEW):
    """Class/Module/Struct/Data all module_exec the block on what they make."""
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    made = rubycall.call(recv, mid, args)
    _drop(frame, recv_at)
    return _exec_on_made(frame, made, w_block)


def _exec_on_made(frame, made, w_block):
    # On the marked stack: no constant names the class yet.
    frame.push(made)
    dispatch.adopt(made)
    cref = _push_cref(_cref_of(w_block.frame), made, True)
    call_block(w_block, [made], NO_KEYWORDS, False, made, cref)
    return frame.pop()


def _in_body_of(frame, recv):
    node = frame.cref
    return node is not None and node.klass == recv


@unroll_safe
def _module_function(frame, recv, recv_at, argc):
    """rb_mod_modfunc: bare form makes every later def private + singleton."""
    if argc == 0:
        frame.module_func = True
        _drop(frame, recv_at)
        return recv
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    # CRuby first, so a name it rejects raises before the registry is touched.
    ret = rubycall.call(recv, MODULE_FUNCTION, args)
    _copy_to_singleton(recv, args)
    return ret


@unroll_safe
def _private_class_method(frame, recv, recv_at, argc):
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    # CRuby first, so a name it rejects raises before the registry is touched.
    ret = rubycall.call(recv, PRIVATE_CLASS_METHOD, args)
    _hide_on_singleton(recv, args)
    return ret


@unroll_safe
def _visibility_pragma(frame, mid, recv, recv_at):
    """Bare private/protected/public: the default every later def takes."""
    frame.private_pragma = (mid == PRIVATE)
    frame.protected_pragma = (mid == PROTECTED)
    _drop(frame, recv_at)
    return recv


@unroll_safe
def _visibility_names(frame, mid, recv, recv_at, argc):
    """private :name; looked up first: CRuby's call adds a private override."""
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    entries = _lookup_all(recv, args)
    # CRuby first, so a name it rejects raises before the registry is touched.
    ret = rubycall.call(recv, mid, args)
    _mark_visibility(recv, args, entries, mid == PRIVATE, mid == PROTECTED)
    return ret


def _lookup_all(klass, args):
    entries = []
    i = 0
    while i < len(args):
        entries.append(dispatch.lookup(klass, symbols.intern(_attr_name(args[i]))))
        i += 1
    return entries


@dont_look_inside
def _mark_visibility(klass, args, entries, private, prot=False):
    i = 0
    while i < len(args):
        entry = entries[i]
        if entry is not None and entry.kind != dispatch.KIND_UNDEF:
            name_mid = symbols.intern(_attr_name(args[i]))
            if entry.kind == dispatch.KIND_ISEQ:
                dispatch.define(klass, name_mid, entry.w_iseq, private,
                                entry.cref, entry.lexical, 0, 0, prot)
            elif entry.kind == dispatch.KIND_BMETHOD:
                dispatch.define_bmethod(klass, name_mid, entry.w_block,
                                        private, prot)
            else:
                dispatch.define_attr(klass, name_mid, entry.ivar,
                                     entry.kind, private, prot)
        i += 1


@unroll_safe
def _remove_or_undef(frame, mid, recv, recv_at, argc):
    """remove_method/undef_method: remove exposes an ancestor's, undef not."""
    args = []
    i = 0
    while i < argc:
        args.append(frame.stack[recv_at + 1 + i])
        i += 1
    _drop(frame, recv_at)
    ret = rubycall.call(recv, mid, args)
    for v in args:
        name_mid = symbols.intern(_attr_name(v))
        if mid == UNDEF_METHOD:
            dispatch.undef_method(recv, name_mid)
        else:
            dispatch.undefine(recv, name_mid)
    return ret


@dont_look_inside
def _hide_on_singleton(recv, args):
    klass = boot.singleton_class(recv)
    if klass == 0 or value.is_immediate(klass):
        return
    for v in args:
        mid = symbols.intern(_attr_name(v))
        entry = dispatch.own_lookup(klass, mid)
        if entry is None or entry.kind != dispatch.KIND_ISEQ:
            continue
        dispatch.define(klass, mid, entry.w_iseq, True, entry.cref,
                        entry.lexical)


@dont_look_inside
def _copy_to_singleton(klass, args):
    for v in args:
        mid = symbols.intern(_attr_name(v))
        entry = dispatch.own_lookup(klass, mid)
        if entry is None or entry.kind != dispatch.KIND_ISEQ:
            continue
        dispatch.define(klass, mid, entry.w_iseq, True, entry.cref,
                        entry.lexical)
        dispatch.define_singleton(klass, mid, entry.w_iseq, entry.cref,
                                  entry.lexical)


def _core_method(frame, mid, recv, recv_at, argc):
    if argc != 3 and mid == CORE_ALIAS:
        raise UnsupportedOperation('core#set_method_alias needs 3 arguments')
    if argc != 2 and mid == CORE_UNDEF:
        raise UnsupportedOperation('core#undef_method needs 2 arguments')
    cbase = frame.stack[recv_at + 1]
    if value.is_immediate(cbase) or not boot.is_class(cbase):
        raise UnsupportedOperation('alias or undef outside a class body')
    name = _sym_mid(frame.stack[recv_at + 2])
    if mid == CORE_UNDEF:
        dispatch.undefine(cbase, name)
        args = [cbase, frame.stack[recv_at + 2]]
        _drop(frame, recv_at)
        ret = rubycall.call(recv, mid, args)
        helpers.refresh()
        return ret
    old = _sym_mid(frame.stack[recv_at + 3])
    # Not own_lookup: `alias` copies whatever the name resolves to, ancestors
    # included, so an inherited method has to stay an RPyYARV entry too.
    entry = dispatch.lookup(cbase, old)
    dispatch.undefine(cbase, name)
    if entry is not None and entry.kind == dispatch.KIND_ISEQ:
        # An RPyYARV method: define installs CRuby's resolving trampoline.
        dispatch.define(cbase, name, entry.w_iseq, entry.private,
                        entry.cref, entry.lexical, entry.mid, entry.owner,
                        entry.prot)
        _drop(frame, recv_at)
        return value.Q_NIL
    if entry is not None:
        # An attr entry: without this the new name lives only in the registry.
        dispatch.define_attr(cbase, name, entry.ivar, entry.kind)
    args = [cbase, frame.stack[recv_at + 2], frame.stack[recv_at + 3]]
    _drop(frame, recv_at)
    ret = rubycall.call(recv, mid, args)
    helpers.refresh()
    return ret


def _alias_method(frame, recv, recv_at):
    """alias_method: an ISEQ alias stays here, not following the old name."""
    new_v = frame.stack[recv_at + 1]
    old_v = frame.stack[recv_at + 2]
    if boot.is_symbol(new_v) and boot.is_symbol(old_v):
        name = symbols.intern(boot.sym_of(new_v))
        old = symbols.intern(boot.sym_of(old_v))
        entry = dispatch.lookup(recv, old)
        if entry is not None:
            dispatch.undefine(recv, name)
            if entry.kind == dispatch.KIND_ISEQ:
                dispatch.define(recv, name, entry.w_iseq, entry.private,
                                entry.cref, entry.lexical,
                                entry.mid, entry.owner, entry.prot)
                _drop(frame, recv_at)
                return new_v
            dispatch.define_attr(recv, name, entry.ivar, entry.kind)
    args = [frame.stack[recv_at + 1], frame.stack[recv_at + 2]]
    _drop(frame, recv_at)
    ret = rubycall.call(recv, ALIAS_METHOD, args)
    helpers.refresh()
    return ret


@dont_look_inside
def _sym_mid(v):
    if not boot.is_symbol(v):
        raise UnsupportedOperation('alias or undef names something '
                                   'that is not a Symbol')
    return symbols.intern(boot.sym_of(v))


def _bmethod_identity(owner, rid, w_block):
    """The MethodEntry a bmethod invocation stands for; None for plain yields."""
    if owner == 0 or owner == value.Q_NIL:
        return None
    mid = rubycall.mid_of_rid(rid)
    if mid == rubycall.NO_MID:
        mid = rubycall.intern_rid(rid)
    if mid == rubycall.NO_MID:
        return None
    # define_method registered a lambda-flagged copy of the block: that copy
    # is the method body, and only it owns a `return`. CRuby's bmethod holds
    # the original proc, so resolve to the registered entry when there is one.
    entry = dispatch.lookup_owned(owner, mid)
    if entry is not None and entry.kind == dispatch.KIND_BMETHOD \
            and entry.w_block is not None and entry.w_block.is_lambda \
            and entry.w_block.w_iseq is w_block.w_iseq:
        return entry
    return dispatch.bmethod_identity(owner, mid, w_block)


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.blocks import call_block
from rpyyarv.interp.callbacks import _call_with_block
from rpyyarv.interp.stackops import _drop
