"""Kernel#require: resolves as load.c does, runs the toplevel ISeq here."""

import os

from rpyyarv import boot
from rpyyarv import bootiseq
from rpyyarv import debug
from rpyyarv import gcroots
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv import prelude
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RubyException
from rpyyarv.frame import Frame

COMPILE_FILE = 'compile_file'
COMPILE_FILE_MID = symbols.intern(COMPILE_FILE)
FOREIGN_REQUIRE_ENV = 'RPYYARV_FOREIGN_REQUIRE'
CRUBY_REQUIRE = symbols.intern('__rpyyarv_cruby_require__')
DELETE = symbols.intern('delete')
LOADED_FEATURES = '$LOADED_FEATURES'

# CRuby dispatches some requires itself (variable.c:3287), past the hook.
OVERRIDE = """module Kernel
  alias_method :__rpyyarv_cruby_require__, :require
  def require(feature)
    __rpyyarv_require__(feature)
  end
  private :require
  # Kernel#require is a module_function, so the singleton copy needs the same
  # body: bundled_gems.rb:60 sends every require through ::Kernel's.
  def self.require(feature)
    __rpyyarv_require__(feature)
  end
end
"""


class _Files(object):
    def __init__(self):
        # Running files, innermost last: require_relative's base (load.c:1042).
        self.stack = []
        # Loads not finished, so a cycle answers false instead of recurring.
        self.loading = {}
        # RPYYARV_DELEGATE_FILES: path substrings to leave to CRuby.
        self.delegated = []


files = _Files()


class _Hook(rubycall.RequireHook):
    def handle(self, mid, arg):
        # Re-running RubyGems/Bundler under RPyYARV redefines global state.
        if os.environ.get(FOREIGN_REQUIRE_ENV) == '1':
            return rubycall.NOT_HANDLED
        if value.is_immediate(arg) or not boot.is_string(arg):
            return rubycall.NOT_HANDLED
        return _require(mid, arg)

    def from_cruby(self, arg):
        v = self.handle(rubycall.REQUIRE, arg)
        if v != rubycall.NOT_HANDLED:
            return v
        return _delegate(arg)


def install(main_path):
    """RPYYARV_NO_REQUIRE=1 leaves every require to CRuby."""
    if os.environ.get('RPYYARV_NO_REQUIRE') == '1':
        return
    spec = os.environ.get('RPYYARV_DELEGATE_FILES')
    if spec is not None and spec != '':
        files.delegated = spec.split(',')
    files.stack.append(main_path)
    rubycall.hooks.require = _Hook()
    prelude.run(OVERRIDE)


def _require(mid, arg):
    fname = arg
    if mid == rubycall.REQUIRE_RELATIVE:
        base = _current_dir()
        if base == '':
            return rubycall.NOT_HANDLED
        candidate = os.path.join(base, boot.str_of(arg))
        if not os.path.exists(candidate) and \
                not os.path.exists(candidate + '.rb'):
            # A delegated CRuby frame's own frame has the real base dir.
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
        # A C extension or unknown name: CRuby's, the requirer stays here.
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
    i = 0
    while i < len(files.delegated):
        if files.delegated[i] in name:
            return _delegate_file(fname, name, 0, 0,
                         'RPYYARV_DELEGATE_FILES names it')
        i += 1

    try:
        result = _compile(path)
    except RubyException:
        # A syntax error reads better out of CRuby's own require.
        return _delegate_file(fname, name, 0, 0,
                     'the embedded CRuby would not compile it')
    if len(result.reasons) > 0:
        return _delegate_file(fname, name, result.total, result.supported,
                     result.reasons[0])

    files.loading[name] = True
    files.stack.append(name)
    # Before the body, as load.c:939 does; else NameError (variable.c:3088).
    boot.provide(path)
    done = False
    try:
        interp.execute(result.w_iseq, Frame(result.w_iseq, boot.top_self()))
        done = True
    finally:
        files.stack.pop()
        del files.loading[name]
        # As load.c:1379: a file that raised is not a loaded feature.
        if not done:
            _unprovide(path)
    debug.count_native()
    debug.record_file(name, result.total, result.supported, '')
    return value.Q_TRUE


def _unprovide(path):
    """Undo boot.provide; the array rb_provide_feature pushed onto."""
    features = boot.gvar_get(LOADED_FEATURES)
    boot.funcallv(features, rubycall.rid(DELETE), [path], DELETE)


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


def _delegate_file(fname, name, total, supported, reason):
    """This one file to CRuby; the file that required it stays on RPyYARV."""
    debug.record_file(name, total, supported, reason)
    return _delegate(fname)


def _delegate(fname):
    """CRuby's own require, under the name OVERRIDE aliased it to."""
    debug.count_foreign(rubycall.REQUIRE)
    return boot.funcallv(boot.top_self(), rubycall.rid(CRUBY_REQUIRE),
                         [fname], CRUBY_REQUIRE)


def _current_dir():
    # The calling ISeq's file: a method body outlives its toplevel.
    path = rubycall.relative.path
    rubycall.relative.path = ''
    # No stamp: CRuby's own frame resolves the path for a delegated file.
    if path == '':
        return ''
    at = path.rfind('/')
    if at < 0:
        return ''
    assert at >= 0
    return path[:at]
