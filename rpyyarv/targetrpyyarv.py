"""RPython translation entry point: embedded CRuby compiles, RPyYARV runs.

--translation-taggedpointers at build time enables experimental immediate integers.
This helps recursive calls but currently slows arithmetic JIT loops.
"""

import os
import sys

# rpython puts only this dir on sys.path; add the repo root so `rpyyarv` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpyyarv import boot
from rpyyarv import bootiseq
from rpyyarv import debug
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv.options import configure_options
from rpyyarv.error import RPyYarvError
from rpyyarv.rlib import StackOverflow, check_stack_overflow


def entry_point(argv):
    try:
        argv = configure_options(argv, interp.jitdriver)
    except RPyYarvError, e:
        print '[rpyyarv] %s' % e.msg
        return 1
    if len(argv) < 2:
        print 'usage: %s [--jit PARAM=VALUE,...] [--debug CHANNELS] [RUBY_OPTIONS] SCRIPT.rb' % argv[0]
        return 1

    iseqw, status = boot.boot(argv)
    if not iseqw:
        return status

    try:
        w_iseq = loader.load(bootiseq.load(iseqw))
        interp.run(w_iseq)
    except RPyYarvError, e:
        print '[rpyyarv] %s' % e.msg
        return 1
    except boot.RubyError, e:
        print '[rpyyarv] Ruby exception in %s' % e.mid
        return 1
    except StackOverflow:
        check_stack_overflow()
        print '[rpyyarv] stack level too deep (SystemStackError)'
        return 1

    return boot.cleanup(0)


def target(driver, args):
    driver.exe_name = 'rpyyarv-runtime-replacing'
    driver.config.translation.taggedpointers = TAGGED_INTS
    return entry_point, None


if __name__ == '__main__':
    import sys
    sys.exit(entry_point(sys.argv))
