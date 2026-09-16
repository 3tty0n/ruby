"""Ruby programs, run end to end: source -> CRuby's compiler -> RPyYARV.

Add a case by dropping a .rb file in test/ruby/. Everything after `__END__`
is the stdout the program must produce; CRuby's parser stops there, so the
file stays a valid Ruby program.
"""

import glob
import os

import pytest

from support import run_dump

PROGRAMS = sorted(glob.glob(os.path.join(os.path.dirname(__file__),
                                         'ruby', '*.rb')))


def expected_output(path):
    f = open(path)
    try:
        text = f.read()
    finally:
        f.close()
    marker = '\n__END__\n'
    assert marker in text, '%s has no __END__ section' % path
    return text.split(marker, 1)[1]


@pytest.mark.parametrize('path', PROGRAMS,
                         ids=[os.path.basename(p)[:-3] for p in PROGRAMS])
def test_ruby_program(path, compile_rb, out):
    run_dump(compile_rb(path))
    assert out.text == expected_output(path)
