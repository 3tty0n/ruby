"""RPython translation entry point: embedded CRuby compiles, RPyYARV runs."""

import os

import boot
import bootiseq
import debug
import gcroots
import interp
import loader
import rubycall
import value
from error import RPyYarvError


def _check_special_consts():
    qfalse, qnil, qtrue, fixnum_flag = boot.special_consts()
    if (qfalse != value.Q_FALSE or qnil != value.Q_NIL
            or qtrue != value.Q_TRUE or fixnum_flag != value.FIXNUM_FLAG):
        debug.note('libruby uses immediate tags '
                   '(Qfalse=%d Qnil=%d Qtrue=%d FIXNUM_FLAG=%d) that value.py '
                   'does not; every VALUE would be mis-decoded'
                   % (qfalse, qnil, qtrue, fixnum_flag))
        return False
    return True


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

    if not _check_special_consts():
        return 1

    # RPYYARV_GC_NO_HOOK leaves the escaped VALUEs unreachable on purpose, so
    # the stress run can show what the hook is buying.
    if os.environ.get('RPYYARV_GC_NO_HOOK') != '1':
        gcroots.install()
    if os.environ.get('RPYYARV_GC_STRESS') == '1':
        rubycall.state.stress = True

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
