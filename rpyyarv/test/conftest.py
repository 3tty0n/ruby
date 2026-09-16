"""Shared setup for every RPyYARV test.

Puts the interpreter's modules on sys.path, undoes the global state a test
leaves behind, and hands out the pieces a test needs from outside: captured
output, and a CRuby that can compile .rb to an ISeq dump.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

import debug
import kernel
from objects.klass import w_object_class

BUILD = os.environ.get('RPYYARV_BUILD',
                       os.path.join(os.path.dirname(ROOT), 'build'))
DUMPER = os.path.join(ROOT, 'scripts', 'dump_iseq.rb')


@pytest.fixture(autouse=True)
def _isolate():
    """A toplevel `def` lands on the one Object; debug flags are global."""
    baseline = w_object_class.methods.methods.copy()
    saved_kernel_write = kernel.write
    saved_debug_write = debug.write
    debug.reset()
    yield
    debug.reset()
    debug.write = saved_debug_write
    kernel.write = saved_kernel_write
    w_object_class.methods.methods = baseline
    w_object_class.method_table_changed()


class Output(object):
    """What the interpreter's builtins printed, while a test runs."""

    def __init__(self):
        self.chunks = []

    @property
    def text(self):
        return ''.join(self.chunks)


@pytest.fixture
def out():
    captured = Output()
    kernel.write = captured.chunks.append
    return captured


@pytest.fixture(scope='session')
def ruby():
    """This tree's ruby; only it emits instructions that match insns.py."""
    exe = os.environ.get('RUBY', os.path.join(BUILD, 'ruby'))
    if not os.path.exists(exe):
        pytest.skip('no ruby in %s; build CRuby first' % BUILD)
    env = dict(os.environ)
    # The build tree's libruby is tagged with its install prefix, not its path
    for var in ('DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
        env[var] = os.pathsep.join([BUILD] + [p for p in [env.get(var)] if p])
    try:
        subprocess.check_output([exe, '-e', ''], env=env,
                                stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as e:
        pytest.skip('%s will not run: %s' % (exe, e))
    return exe, env


@pytest.fixture(scope='session')
def compile_rb(ruby):
    """Compiles a .rb path to the ISeq dump text loader.load_dump() reads."""
    exe, env = ruby

    def compile_rb(path):
        text = subprocess.check_output([exe, DUMPER, path], env=env)
        if not isinstance(text, str):
            text = text.decode('utf-8')
        return text

    return compile_rb
