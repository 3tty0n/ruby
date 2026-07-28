"""RPython translation entry point
"""

import boot


def probe(iseqw):
    """Dump the intercepted ISeq. Placeholder until interp.py lands."""
    print '[rpyyarv] === Success: intercepted main ISeq ==='
    print '[rpyyarv] label         : %s' % boot.inspect(boot.call0(iseqw, 'label'))
    print '[rpyyarv] absolute_path : %s' % boot.inspect(
        boot.call0(iseqw, 'absolute_path'))

    ary = boot.call0(iseqw, 'to_a')
    print '[rpyyarv] to_a.size     : %d' % boot.rb_ary_len(ary)

    insns = boot.rb_ary_entry(ary, boot.rb_ary_len(ary) - 1)
    n_elem = boot.rb_ary_len(insns)
    n_insn = 0
    n_label = 0
    n_lineno = 0
    i = 0
    while i < n_elem:
        e = boot.rb_ary_entry(insns, i)
        if boot.is_array(e):
            n_insn += 1
        elif boot.is_symbol(e):
            n_label += 1
        elif boot.is_fixnum(e):
            n_lineno += 1
        i += 1
    print '[rpyyarv] elements: %d (insn %d / label %d / lineno %d)' % (
        n_elem, n_insn, n_label, n_lineno)

    shown = 0
    i = 0
    while i < n_elem and shown < 6:
        e = boot.rb_ary_entry(insns, i)
        if boot.is_array(e):
            s = boot.inspect(e)
            if len(s) > 100:
                s = s[:100] + '...'
            print '[rpyyarv]   %s' % s
            shown += 1
        i += 1

    print '[rpyyarv] ruby_run_node() was never called.'


def entry_point(argv):
    if len(argv) < 2:
        print 'usage: %s SCRIPT.rb' % argv[0]
        return 1

    iseqw, status = boot.boot(argv)
    if not iseqw:
        return status

    try:
        probe(iseqw)
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
