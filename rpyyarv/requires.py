"""Kernel#require and #require_relative, served by RPyYARV itself.

A file CRuby loads defines its methods into CRuby's method tables, which
RPyYARV's registry never sees, so every later call into it leaves through
rb_funcallv. Here the path is resolved the way load.c does, the file is
compiled by the embedded CRuby, and its toplevel ISeq runs in RPyYARV with
self = main, which puts its `def`s where dispatch.lookup can find them.
A file RPyYARV cannot represent is handed to CRuby on its own, not the whole
program -- but the file that required it has to follow it there; see _punt.
"""

import os

import boot
import bootiseq
import debug
import gcroots
import interp
import loader
import rubycall
import value
from error import RubyException
from frame import Frame

COMPILE_FILE = 'compile_file'


class _PuntChain(Exception):
    """A require inside a natively running file went to CRuby, so that file
    must go too. Unwinds its toplevel ISeq."""


class _Files(object):
    def __init__(self):
        # The files whose toplevel ISeq is running, innermost last; the base
        # for require_relative, which cannot use rb_current_realfilepath
        # because RPyYARV pushes no CRuby frame (load.c:1042).
        self.stack = []
        # Expanded paths whose load has not finished, so a cycle answers
        # false instead of recurring.
        self.loading = {}


files = _Files()


class _Hook(rubycall.RequireHook):
    def handle(self, mid, arg):
        if value.is_immediate(arg) or not boot.is_string(arg):
            return rubycall.NOT_HANDLED
        return _require(mid, arg)


def install(main_path):
    """RPYYARV_NO_REQUIRE=1 leaves every require to CRuby, as before."""
    if os.environ.get('RPYYARV_NO_REQUIRE') == '1':
        return
    files.stack.append(main_path)
    rubycall.hooks.require = _Hook()


def _require(mid, arg):
    fname = arg
    if mid == rubycall.REQUIRE_RELATIVE:
        base = _current_dir()
        if base == '':
            return rubycall.NOT_HANDLED
        fname = boot.absolute_path(arg, boot.str_new(base))
    # Held, not pinned: a require in a loop would pin one string per turn.
    gcroots.hold(fname)
    try:
        return _load(fname)
    finally:
        gcroots.release(fname)


def _load(fname):
    kind, path = boot.require_resolve(fname)
    if kind == boot.REQ_LOADED:
        return value.Q_FALSE
    if kind != boot.REQ_RB:
        # A C extension, or a name no $LOAD_PATH entry holds: CRuby's either
        # way, and not a fallback, so the requiring file stays on RPyYARV.
        return _delegate(fname)
    gcroots.hold(path)
    try:
        return _load_rb(fname, path)
    finally:
        gcroots.release(path)


def _load_rb(fname, path):
    name = boot.str_of(path)
    if name in files.loading:
        return value.Q_FALSE

    try:
        result = _compile(path)
    except RubyException:
        # A syntax error reads better out of CRuby's own require.
        return _punt(fname, name, 0, 0,
                     'the embedded CRuby would not compile it')
    if len(result.reasons) > 0:
        return _punt(fname, name, result.total, result.supported,
                     result.reasons[0])

    files.loading[name] = True
    files.stack.append(name)
    punted = False
    try:
        interp.execute(result.w_iseq, Frame(result.w_iseq, boot.top_self()))
    except _PuntChain:
        punted = True
    finally:
        files.stack.pop()
        del files.loading[name]
    if punted:
        return _punt(fname, name, result.total, result.supported,
                     'it requires a file only CRuby can load')
    debug.count_native()
    debug.record_file(name, result.total, result.supported, '')
    # After the body, as CRuby does (load.c:1379): a file that raised is not
    # a loaded feature.
    boot.provide(path)
    return value.Q_TRUE


def _compile(path):
    """The file through the embedded CRuby's compiler and RPyYARV's loader."""
    rubyvm = boot.const_get(value.core_class(value.C_OBJECT),
                            boot.intern('RubyVM'))
    iseq_class = boot.const_get(rubyvm, boot.intern('InstructionSequence'))
    iseqw = boot.funcallv(iseq_class, boot.intern(COMPILE_FILE), [path],
                          COMPILE_FILE)
    gcroots.hold(iseqw)
    try:
        return loader.load(bootiseq.load(iseqw))
    finally:
        gcroots.release(iseqw)


def _punt(fname, name, total, supported, reason):
    """This one file to CRuby; the rest of the program stays on RPyYARV.

    Its `def`s land in CRuby's method tables, so a subclass RPyYARV defined
    could no longer override a method CRuby dispatches: the file that
    required it has to go to CRuby too. That file is re-run from the top,
    which is only sound because a require sits above the definitions.
    """
    debug.record_file(name, total, supported, reason)
    v = _delegate(fname)
    if len(files.stack) > 1:
        raise _PuntChain()
    return v


def _delegate(fname):
    """CRuby's own require, which keeps its own $LOADED_FEATURES bookkeeping."""
    debug.count_foreign()
    return boot.funcallv(boot.top_self(), rubycall.rid(rubycall.REQUIRE),
                         [fname], 'require')


def _current_dir():
    if len(files.stack) == 0:
        return ''
    path = files.stack[len(files.stack) - 1]
    at = path.rfind('/')
    if at < 0:
        return ''
    assert at >= 0
    return path[:at]
