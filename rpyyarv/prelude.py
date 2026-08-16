"""prelude.rb, compiled by the embedded CRuby and run before the main script; read at import time, so translation bakes the source into the binary."""

import os

from rpyyarv import boot
from rpyyarv import bootiseq
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.frame import Frame

COMPILE = symbols.intern('compile')

_HERE = os.path.dirname(os.path.abspath(__file__))
_f = open(os.path.join(_HERE, 'prelude.rb'))
SOURCE = _f.read()
_f.close()


def _compile(source):
    """RubyVM::InstructionSequence.compile(source) -> an iseqw bootiseq reads."""
    rubyvm = boot.const_get(value.core_class(value.C_OBJECT),
                            boot.intern('RubyVM'))
    iseq_class = boot.const_get(rubyvm, boot.intern('InstructionSequence'))
    src = boot.str_new(source)
    # Pinned rather than kept on the RPython stack: CRuby's GC never scans it.
    boot.gc_register(src)
    iseqw = boot.funcallv(iseq_class, boot.intern('compile'), [src], COMPILE)
    boot.gc_register(iseqw)
    return iseqw


def run(source):
    """Ruby source through the embedded CRuby's compiler, run by RPyYARV with self = main."""
    w_iseq = loader.load_strict(bootiseq.load(_compile(source)))
    interp.execute(w_iseq, Frame(w_iseq, boot.top_self()))


def install():
    if os.environ.get('RPYYARV_NO_PRELUDE') == '1':
        return
    run(SOURCE)
