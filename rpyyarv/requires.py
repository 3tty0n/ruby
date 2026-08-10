"""Kernel#require/#require_relative: resolves the path as load.c does, compiles via embedded CRuby, and runs the toplevel ISeq in RPyYARV with self = main."""

import os

from rpyyarv import boot
from rpyyarv import bootiseq
from rpyyarv import debug
from rpyyarv import gcroots
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RubyException
from rpyyarv.frame import Frame

COMPILE_FILE = 'compile_file'
COMPILE_FILE_MID = symbols.intern(COMPILE_FILE)


class _Files(object):
    def __init__(self):
        # The files whose toplevel ISeq is running, innermost last; require_relative's base since RPyYARV pushes no CRuby frame (load.c:1042).
        self.stack = []
        # Expanded paths whose load has not finished, so a cycle answers false instead of recurring.
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
        # A C extension, or a name no $LOAD_PATH entry holds: CRuby's either way, and not a fallback, so the requiring file stays on RPyYARV.
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
    try:
        interp.execute(result.w_iseq, Frame(result.w_iseq, boot.top_self()))
    finally:
        files.stack.pop()
        del files.loading[name]
    debug.count_native()
    debug.record_file(name, result.total, result.supported, '')
    # After the body, as CRuby does (load.c:1379): a file that raised is not a loaded feature.
    boot.provide(path)
    return value.Q_TRUE


def _compile(path):
    """The file through the embedded CRuby's compiler and RPyYARV's loader."""
    rubyvm = boot.const_get(value.core_class(value.C_OBJECT),
                            boot.intern('RubyVM'))
    iseq_class = boot.const_get(rubyvm, boot.intern('InstructionSequence'))
    iseqw = boot.funcallv(iseq_class, boot.intern(COMPILE_FILE), [path],
                          COMPILE_FILE_MID)
    gcroots.hold(iseqw)
    try:
        return loader.load(bootiseq.load(iseqw))
    finally:
        gcroots.release(iseqw)


def _punt(fname, name, total, supported, reason):
    """This one file to CRuby; the file that required it stays on RPyYARV."""
    debug.record_file(name, total, supported, reason)
    return _delegate(fname)


def _delegate(fname):
    """CRuby's own require, which keeps its own $LOADED_FEATURES bookkeeping."""
    debug.count_foreign(rubycall.REQUIRE)
    return boot.funcallv(boot.top_self(), rubycall.rid(rubycall.REQUIRE),
                         [fname], rubycall.REQUIRE)


def _current_dir():
    if len(files.stack) == 0:
        return ''
    path = files.stack[len(files.stack) - 1]
    at = path.rfind('/')
    if at < 0:
        return ''
    assert at >= 0
    return path[:at]
