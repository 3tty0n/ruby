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

import support


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
    exe, env = support.ruby_exe()
    if exe is None:
        pytest.skip(env)
    return exe, env


@pytest.fixture(scope='session')
def compile_rb(ruby):
    """Compiles a .rb path to the ISeq dump text loader.load_dump() reads."""
    return lambda path: support.compile_rb(path, ruby)


@pytest.fixture
def ruby_program(ruby, out):
    """Runs Ruby source on RPyYARV -- source, CRuby's compiler, ISeq, us.

        def test_addition(ruby_program):
            assert ruby_program('puts 1 + 2') == '3\n'
    """
    def ruby_program(source):
        support.run_dump(support.compile_source(source, ruby))
        return out.text

    return ruby_program
