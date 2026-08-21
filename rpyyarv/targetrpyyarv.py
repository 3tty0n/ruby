"""RPython translation entry point: embedded CRuby compiles, RPyYARV runs."""

import os

from rpyyarv import boot
from rpyyarv import bootiseq
from rpyyarv import debug
from rpyyarv import dispatch
from rpyyarv import fibers
from rpyyarv import gcroots
from rpyyarv import helpers
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv import prelude
from rpyyarv import requires
from rpyyarv import rubycall
from rpyyarv import value
from rpyyarv.error import RPyYarvError, RubyException
from rpyyarv.rlib import StackOverflow, check_stack_overflow, set_stack_length

# libruby shares the 8 MB main stack and checks itself, so take half.
STACK_LIMIT = 4 * 1024 * 1024


def _raise_stack_limit():
    want = STACK_LIMIT
    spec = os.environ.get('RPYYARV_STACK_LIMIT')
    if spec is not None:
        try:
            want = int(spec)
        except ValueError:
            want = STACK_LIMIT
    got = set_stack_length(want)
    if spec is not None:
        debug.note('stack limit %d byte(s)' % got)


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

    _raise_stack_limit()

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

    if not helpers.check_struct_layout():
        debug.note('libruby lays out RStruct differently than value.py '
                   'assumes; the Struct fast paths would misread it')
        return 1

    debug.configure_coverage()
    dispatch.install()

    if not helpers.check_float_layout():
        debug.note('libruby lays out RFloat or flonums differently than '
                   'value.py assumes; the Float fast paths would misread it')
        return 1

    if not helpers.check_flonum_encoding():
        debug.note('value.py encodes flonums differently than libruby does; '
                   'every Float result would be a different number')
        return 1

    if not helpers.refresh():
        debug.note('boot_shim.c watches a different set of basic operators '
                   'than helpers.py names; a redefined operator would go '
                   'unnoticed')
        return 1
    interp.install()

    # RPYYARV_GC_NO_HOOK leaves the escaped VALUEs unreachable on purpose.
    if os.environ.get('RPYYARV_GC_NO_HOOK') != '1':
        gcroots.install()
        fibers.install()
    if os.environ.get('RPYYARV_GC_STRESS') == '1':
        rubycall.stress.flag = True

    try:
        prelude.install()
        dispatch.enable_trampolines()
        program = bootiseq.load(iseqw)
        result = loader.load(program)
        if len(result.reasons) > 0:
            # No per-method split: one unsupported iseq sends the file to CRuby.
            debug.record_file(program.path, result.total, result.supported,
                              result.reasons[0])
            debug.note('running under CRuby instead: %d unsupported iseq(s), '
                       'first %s' % (len(result.reasons), result.reasons[0]))
            debug.report()
            return interp.run_in_cruby()
        debug.record_file(program.path, result.total, result.supported, '')
        requires.install(program.path)
        interp.run(result.w_iseq)
        debug.report()
    except RubyException, e:
        # Nothing rescued it: CRuby prints it and picks the exit status.
        return boot.cleanup_with_error(e.value)
    except RPyYarvError, e:
        print '[rpyyarv] %s' % e.msg
        return 1
    except boot.RubyError, e:
        print '[rpyyarv] Ruby exception in %s' % e.mid
        return 1
    except StackOverflow:
        check_stack_overflow()
        print '[rpyyarv] %s' % interp.STACK_TOO_DEEP
        return 1

    return boot.cleanup(0)


def target(driver, args):
    driver.exe_name = 'rpyyarv'
    # The shadowstack copy a fiber switch saves is generated only under this.
    driver.config.translation.continuation = True
    return entry_point, None


if __name__ == '__main__':
    import sys
    sys.exit(entry_point(sys.argv))
