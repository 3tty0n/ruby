"""RPython translation entry point: embedded CRuby compiles, RPyYARV runs."""

import os
import sys

# rpython puts only this dir on sys.path; add the repo root so `rpyyarv` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpyyarv import boot
from rpyyarv import bootiseq
from rpyyarv import debug
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv.error import RPyYarvError


def entry_point(argv):
    if len(argv) < 2:
        print 'usage: %s SCRIPT.rb' % argv[0]
        return 1

    for name in debug.configure_from_env():
        debug.note('unknown RPYYARV_DEBUG channel %s; known: %s'
                   % (name, debug.CHANNELS))

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

    return boot.cleanup(0)


def target(driver, args):
    driver.exe_name = 'rpyyarv-runtime-replacing'
    return entry_point, None


if __name__ == '__main__':
    import sys
    sys.exit(entry_point(sys.argv))
