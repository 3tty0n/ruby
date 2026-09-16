"""The interpreter run through RPython's low-level interpreter.

`ll_run` annotates, rtypes and executes interp.execute() the way a
translation would, so a test here catches what plain CPython lets past:
an unannotatable type, a list RPython may not resize, a bad downcast.

Needs Python 2 and the pypy checkout, so `make test` skips it; run it with

    make test-llinterp        # or: python2 test/test_llinterp.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# pypy/ ships its own pytest and py; only Python 2 may see them.
if sys.version_info[0] == 2:
    sys.path.insert(0, os.path.join(ROOT, 'pypy'))

import pytest

import loader
import support
from frame import Frame
from objects.array import W_Array
from objects.main import W_Main
from objects.string import W_String
from objects.transparent import w_nil

try:
    from rpython.rtyper.test.test_llinterp import interpret
except ImportError:
    interpret = None

pytestmark = pytest.mark.skipif(
    interpret is None, reason='needs Python 2 and pypy/: make test-llinterp')


def _seed():
    """llinterp sees only the graph it is given, and a field with no writer
    in it has no type. Building one of each keeps execute() annotatable."""
    return len(W_Array([w_nil]).items_w) + len(W_String('x').strval)


def ll_run(w_iseq):
    """Runs a loaded ISeq under llinterp and returns its Integer result.

    The ISeq is loaded here, in plain Python, and reaches the graph as a
    prebuilt constant -- exactly as the boot path hands one over after
    translation.
    """
    import interp

    def entry():
        if _seed() < 0:
            return -1
        return interp.execute(w_iseq, Frame(w_iseq, W_Main())).int_w()

    return interpret(entry, [])


def ll_run_dump(text):
    return ll_run(loader.load_dump(text))


def test_locals_and_a_call():
    # test/locals.rb: f(9, 4) through opt_send_without_block
    assert ll_run_dump(support.fixture('locals.iseq')) == 5


def test_recursion():
    """Ruby source all the way down to llinterp; keep it small, llinterp is
    thousands of times slower than the translated interpreter."""
    exe, env = support.ruby_exe()
    if exe is None:
        pytest.skip(env)
    assert ll_run_dump(support.compile_source("""
        def fib(n)
          if n < 2
            n
          else
            fib(n - 1) + fib(n - 2)
          end
        end

        fib(10)
    """, (exe, env))) == 55


if __name__ == '__main__':
    # Python 2 has no modern pytest here, so run the tests directly.
    failed = 0
    for name in sorted(n for n in dir() if n.startswith('test_')):
        try:
            globals()[name]()
        except Exception as e:
            failed += 1
            print('FAIL %s: %r' % (name, e))
        else:
            print('ok %s' % name)
    sys.exit(1 if failed else 0)
