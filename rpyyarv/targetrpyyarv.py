"""RPython translation entry point: embedded CRuby compiles, RPyYARV runs."""

import boot
import bootiseq
import interp
import loader
from error import RPyYarvError


def entry_point(argv):
    if len(argv) < 2:
        print 'usage: %s SCRIPT.rb' % argv[0]
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

    return boot.cleanup(0)


def target(driver, args):
    driver.exe_name = 'rpyyarv'
    return entry_point, None


if __name__ == '__main__':
    import sys
    sys.exit(entry_point(sys.argv))
