"""RPython translation entry point: embedded CRuby compiles, RPyYARV runs."""

import os

import boot
import bootiseq
import debug
import interp
import loader
from error import RPyYarvError


def _dump_iseqw(iseqw):
    os.write(1, '[dump] Stage1 VALUE iseqw = %d\n' % boot.iseqw_as_int(iseqw))


def _dump_raw_program(program):
    os.write(1, '[dump] Stage2 RawProgram: %d iseq(s)\n' % len(program.iseqs))
    for i in range(len(program.iseqs)):
        raw = program.iseqs[i]
        os.write(1, '  [%d] name=%s type=%s nlocals=%d stack_max=%d '
                 'lead_num=%d insns=%d\n'
                 % (i, raw.name, raw.type, raw.nlocals, raw.stack_max,
                    raw.lead_num, len(raw.insns)))
        for insn in raw.insns:
            ops = ''
            for op in insn.operands:
                if ops:
                    ops = ops + ' '
                ops = ops + op.describe()
            os.write(1, '    %s %s\n' % (insn.name, ops))


def _dump_w_iseq(w_iseq):
    os.write(1, '[dump] Stage3 W_ISeq: name=%s nlocals=%d stack_max=%d '
             'code_len=%d consts=%d\n'
             % (w_iseq.name, w_iseq.nlocals, w_iseq.stack_max,
                len(w_iseq.code), len(w_iseq.consts)))
    code_str = ''
    for i in range(len(w_iseq.code)):
        if i > 0:
            code_str = code_str + ' '
        code_str = code_str + str(w_iseq.code[i])
    os.write(1, '  code: [%s]\n' % code_str)
    for i in range(len(w_iseq.consts)):
        os.write(1, '  const[%d]: %s\n' % (i, w_iseq.consts[i].repr()))


def entry_point(argv):
    if len(argv) < 2:
        print 'usage: %s SCRIPT.rb' % argv[0]
        return 1

    for name in debug.configure_from_env():
        debug.note('unknown RPYYARV_DEBUG channel %s; known: %s'
                   % (name, debug.CHANNELS))

    iseqw, status = boot.boot(argv)
    _dump_iseqw(iseqw)
    if not iseqw:
        return status

    try:
        raw_program = bootiseq.load(iseqw)
        _dump_raw_program(raw_program)
        w_iseq = loader.load(raw_program)
        _dump_w_iseq(w_iseq)
        interp.run(w_iseq)
    except RPyYarvError, e:
        print '[rpyyarv] %s' % e.msg
        return 1
    except boot.RubyError, e:
        print '[rpyyarv] Ruby exception in %s' % e.mid
        return 1

    return boot.cleanup(0)


def target(driver, args):
    driver.exe_name = 'rpyyarv-vm'
    return entry_point, None


if __name__ == '__main__':
    import sys
    sys.exit(entry_point(sys.argv))