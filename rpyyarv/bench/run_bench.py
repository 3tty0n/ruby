#!/usr/bin/env python3
"""Run a benchmark file, unchanged, on Ruby implementations; one CSV row per iteration.

usage (from ~/ruby-rpyyarv/rpyyarv):
  python3 bench/run_bench.py ../benchmark/app_answer.rb --impl rpyyarv [--iters 100] [--runs 10]
"""
import argparse
import csv
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))   # ~/ruby-rpyyarv/rpyyarv/bench
TOP = os.path.dirname(os.path.dirname(HERE))        # ~/ruby-rpyyarv
BUILD = os.environ.get('RPYYARV_BUILD', os.path.join(TOP, 'build'))
RUBY = os.path.join(BUILD, 'ruby')
RPYYARV = os.environ.get('RPYYARV_BIN', os.path.join(TOP, 'rpyyarv-jit'))
PRELUDE = '-r' + os.path.join(HERE, 'prelude.rb')
# Results live outside the repository: ~/rpyyarv-results
RESULTS = os.environ.get('RPYYARV_RESULTS',
                         os.path.join(os.path.dirname(TOP), 'rpyyarv-results'))

IMPLS = {
    'rpyyarv':     [RPYYARV, '--disable-gems'],
    'cruby':       [RUBY, '--disable-gems', PRELUDE],
    'yjit':        [RUBY, '--yjit', '--disable-gems', PRELUDE],
    'zjit':        [RUBY, '--zjit', '--disable-gems', PRELUDE],
    'truffleruby': ['truffleruby', PRELUDE],
}

DEF_START = re.compile(r'^(def|class|module)\b')
ENDLESS_DEF = re.compile(r'^def\s[^=]*\)\s*=[^=~>]')
MARK = '__BENCH__ '


def wrap(path, iters):
    """Keep toplevel definitions; run everything else `iters` times, timed."""
    lines = open(path).read().split('\n')
    defs, body = [], []
    i = 0
    while i < len(lines) and lines[i] != '__END__':
        line = lines[i]
        if DEF_START.match(line) and not ENDLESS_DEF.match(line):
            j = i
            while lines[j] != 'end':
                j += 1
                if j == len(lines):
                    sys.exit('%s:%d: no toplevel `end` for this definition' % (path, i + 1))
            defs.extend(lines[i:j + 1])
            i = j + 1
            continue
        (defs if DEF_START.match(line) else body).append(line)
        i += 1
    out = defs + [
        '__bench_i = 0',
        'while __bench_i < %d' % iters,
        '  __bench_t0 = bench_now_ns',
    ] + ['  ' + l if l.strip() else '' for l in body] + [
        '  __bench_t1 = bench_now_ns',
        '  puts "%s#{__bench_t1 - __bench_t0}"' % MARK,
        '  __bench_i = __bench_i + 1',
        'end',
    ]
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bench')
    ap.add_argument('--impl', action='append', choices=sorted(IMPLS), required=True)
    ap.add_argument('--iters', type=int, default=100)
    ap.add_argument('--runs', type=int, default=10)
    ap.add_argument('--out', help='CSV to append to (default: ~/rpyyarv-results/<bench>.csv)')
    a = ap.parse_args()

    name = os.path.splitext(os.path.basename(a.bench))[0]
    os.makedirs(os.path.join(RESULTS, 'gen'), exist_ok=True)
    gen = os.path.join(RESULTS, 'gen', name + '.rb')
    with open(gen, 'w') as f:
        f.write(wrap(a.bench, a.iters))
    out = a.out or os.path.join(RESULTS, name + '.csv')

    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = os.pathsep.join(
        [BUILD] + [p for p in [env.get('LD_LIBRARY_PATH')] if p])

    new = not os.path.exists(out)
    with open(out, 'a', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(['bench', 'impl', 'run', 'iter', 'ns'])
        for impl in a.impl:
            for run in range(a.runs):
                p = subprocess.run(IMPLS[impl] + [gen], env=env,
                                   capture_output=True, text=True)
                times = [int(l[len(MARK):]) for l in p.stdout.splitlines()
                         if l.startswith(MARK)]
                if p.returncode != 0 or len(times) != a.iters:
                    sys.exit('[%s run %d] exit=%d, %d/%d samples\n%s%s'
                             % (impl, run, p.returncode, len(times), a.iters,
                                p.stdout[-2000:], p.stderr[-2000:]))
                for i, ns in enumerate(times):
                    w.writerow([name, impl, run, i, ns])
                f.flush()
                s = sorted(times)
                print('%-12s run %2d  first %8.2f ms  median %8.2f ms'
                      % (impl, run, times[0] / 1e6, s[len(s) // 2] / 1e6))
    print('wrote', out)


if __name__ == '__main__':
    main()