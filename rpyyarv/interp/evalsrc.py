"""Runtime eval of Ruby source."""
# No absolute_import here: it would change the level operand of the
# in-function imports below. Every import in this file is absolute.

from rpyyarv import boot
from rpyyarv import dispatch
from rpyyarv import gcroots
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RPyYarvError, RubyException
from rpyyarv.frame import Frame
from rpyyarv.rlib import dont_look_inside, raw_word

from rpyyarv.interp.consts_ids import COMPILE, EVAL, INSTANCE_EVAL, LOCAL_VARIABLE_SET
from rpyyarv.interp.cref import _cref_of, _push_cref
from rpyyarv.interp.args import _declare_locals, _slot_named


@dont_look_inside
def _eval_rpy(frame, klass, recv, source):
    """The two binding-free eval forms used by optcarrot's code generator."""
    if value.is_immediate(source) or not boot.is_string(source):
        return value.Q_UNDEF
    if dispatch.owner_of(klass, EVAL) != send_owners.eval:
        return value.Q_UNDEF
    name = boot.str_of(source)
    if name.startswith('def self.run'):
        from rpyyarv import bootiseq
        from rpyyarv import loader
        from rpyyarv import prelude
        w_iseq = loader.load_strict(bootiseq.load(prelude._compile(name)))
        return execute(w_iseq, Frame(w_iseq, recv, frame.cref, frame.entry))
    if len(name) == 0 or name[0] < 'A' or name[0] > 'Z':
        return value.Q_UNDEF
    i = 1
    while i < len(name):
        c = name[i]
        if not ((c >= 'A' and c <= 'Z') or (c >= 'a' and c <= 'z')
                or (c >= '0' and c <= '9') or c == '_'):
            return value.Q_UNDEF
        i += 1
    return _const_lexical(_cref_of(frame), symbols.intern(name))


@dont_look_inside
def _eval_receiver(recv):
    """Out through CRuby a string eval's defs would lose their cref home."""
    if dispatch.is_known_class(recv) or dispatch.is_known_module(recv):
        return True
    if value.is_immediate(recv):
        return False
    kind = raw_word(recv, value.FLAGS_WORD) & value.T_MASK
    if kind != value.T_CLASS and kind != value.T_MODULE:
        return False
    dispatch.adopt(recv)
    return True


def _module_eval_rpy(frame, recv, source, file_v, line_v):
    """String class_eval/module_eval keeping the caller's lexical CREF."""
    if value.is_immediate(source) or not boot.is_string(source):
        return value.Q_UNDEF
    from rpyyarv import bootiseq
    from rpyyarv import loader
    text = boot.str_of(source)
    line = value.fix2int(line_v) if value.is_fixnum(line_v) else 1
    names = _eval_local_names(frame, text)
    if len(names) > 0:
        # eval_string_with_cref runs in the caller's scope: declare its locals.
        text = _declare_locals(names) + text
        line -= 1
    # An eval RPyYARV gives up on drops its ISeqs; unroot their pools too.
    mark = gcroots.consts_mark()
    try:
        iseqw = _compile_eval(text, file_v, line)
        gcroots.hold(iseqw)
        try:
            result = loader.load(bootiseq.load(iseqw))
        finally:
            gcroots.release(iseqw)
    except RubyException:
        gcroots.consts_rollback(mark)
        return value.Q_UNDEF
    except RPyYarvError:
        gcroots.consts_rollback(mark)
        return value.Q_UNDEF
    if len(result.reasons) > 0:
        gcroots.consts_rollback(mark)
        return value.Q_UNDEF
    # Not by_eval: eval_under pushes the receiver's cref (vm_eval.c:2269).
    cref = _push_cref(_cref_of(frame), recv)
    callee = Frame(result.w_iseq, recv, cref, frame.entry)
    _copy_eval_locals(frame, callee, result.w_iseq, False)
    try:
        return execute(result.w_iseq, callee)
    finally:
        # ponytail: locals copied in/out; share the env if a Proc must see them.
        _copy_eval_locals(frame, callee, result.w_iseq, True)


@dont_look_inside
def _compile_eval(text, file_v, line):
    """Compile eval source at the caller's file and line, for __FILE__."""
    rubyvm = boot.const_get(value.core_class(value.C_OBJECT),
                            boot.intern('RubyVM'))
    iseq_class = boot.const_get(rubyvm, boot.intern('InstructionSequence'))
    src = boot.str_new(text)
    gcroots.hold(src)
    try:
        return boot.funcallv(iseq_class, boot.intern('compile'),
                             [src, file_v, file_v, value.int2fix(line)],
                             COMPILE)
    finally:
        gcroots.release(src)


@dont_look_inside
def _binding_rpy(frame):
    """Kernel#binding: a CRuby Binding refilled from this frame's locals."""
    src = boot.str_new('binding')
    gcroots.hold(src)
    try:
        b = rubycall.call1(frame.self_val, INSTANCE_EVAL, src)
    finally:
        gcroots.release(src)
    if value.is_immediate(b):
        return value.Q_UNDEF
    gcroots.hold(b)
    try:
        f = frame
        n = 0
        seen = {}
        while f is not None and n < MAX_SCOPES:
            names = f.w_iseq.local_names
            i = 0
            while i < len(names):
                name = names[i]
                if _is_local_name(name) and name not in seen:
                    seen[name] = True
                    rubycall.call2(b, LOCAL_VARIABLE_SET,
                                   rubycall.sym_value(symbols.intern(name)),
                                   f.local_get(i))
                i += 1
            f = f.defining_frame
            n += 1
    finally:
        gcroots.release(b)
    # ponytail: a copy, so an assignment through it never reaches our frame.
    return b


def _is_local_name(name):
    """A name the eval source may declare; `_1` and `it` are the parser's."""
    if len(name) == 0 or name == 'it':
        return False
    c = name[0]
    if not ((c >= 'a' and c <= 'z') or c == '_'):
        return False
    i = 1
    while i < len(name):
        c = name[i]
        if not ((c >= 'a' and c <= 'z') or (c >= 'A' and c <= 'Z')
                or (c >= '0' and c <= '9') or c == '_'):
            return False
        i += 1
    return not (len(name) == 2 and name[0] == '_'
                and name[1] >= '0' and name[1] <= '9')


def _eval_local_names(frame, text):
    """Every local the string names, innermost first, out to the method's."""
    names = []
    seen = {}
    f = frame
    n = 0
    while f is not None and n < MAX_SCOPES:
        for name in f.w_iseq.local_names:
            if _is_local_name(name) and name not in seen \
                    and text.find(name) >= 0:
                seen[name] = True
                names.append(name)
        f = f.defining_frame
        n += 1
    return names


def _copy_eval_locals(frame, callee, w_iseq, back):
    """Caller locals in and back out, so an assignment reaches the caller."""
    f = frame
    n = 0
    seen = {}
    while f is not None and n < MAX_SCOPES:
        names = f.w_iseq.local_names
        i = 0
        while i < len(names):
            name = names[i]
            if _is_local_name(name) and name not in seen:
                seen[name] = True
                at = _slot_named(w_iseq, name)
                if at >= 0:
                    if back:
                        f.local_set(i, callee.local_get(at))
                    else:
                        callee.local_set(at, f.local_get(i))
            i += 1
        f = f.defining_frame
        n += 1


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.sends import send_owners
from rpyyarv.interp.throws import MAX_SCOPES
from rpyyarv.interp.consts import _const_lexical
from rpyyarv.interp.execute import execute
