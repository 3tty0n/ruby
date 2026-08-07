"""RPython translation entry point: embedded CRuby compiles, RPyYARV runs."""

import os

import boot
import bootiseq
import debug
import dispatch
import gcroots
import helpers
import interp
import loader
import prelude
import rubycall
import value
from error import RPyYarvError, RubyException


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

    if not dispatch.check_object_layout():
        debug.note('libruby lays out RObject/shape ids differently than '
                   'value.py assumes; the ivar fast path would misread it')
        return 1

    if not helpers.check_array_layout():
        debug.note('libruby lays out RArray differently than value.py '
                   'assumes; the Array fast paths would misread it')
        return 1

    debug.configure_coverage()
    dispatch.install()

    if not helpers.refresh():
        debug.note('boot_shim.c watches a different set of basic operators '
                   'than helpers.py names; a redefined operator would go '
                   'unnoticed')
        return 1
    interp.install()

    # RPYYARV_GC_NO_HOOK leaves the escaped VALUEs unreachable on purpose.
    if os.environ.get('RPYYARV_GC_NO_HOOK') != '1':
        gcroots.install()
    if os.environ.get('RPYYARV_GC_STRESS') == '1':
        rubycall.stress.flag = True

    try:
        prelude.install()
        result = loader.load(bootiseq.load(iseqw))
        debug.report_iseqs(result.supported, result.total)
        if len(result.reasons) > 0:
            # No per-method granularity: a method body RPyYARV cannot run has
            # to be defined into CRuby, which needs the cref and the enclosing
            # binding RPyYARV's frames do not carry.
            debug.note('running under CRuby instead: %d unsupported iseq(s), '
                       'first %s' % (len(result.reasons), result.reasons[0]))
            return interp.run_in_cruby()
        interp.run(result.w_iseq)
        debug.report_sends()
    except RubyException, e:
        # Nothing rescued it: CRuby prints it and picks the exit status.
        return boot.cleanup_with_error(e.value)
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
