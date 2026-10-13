#!/usr/bin/env python3
"""Run a benchmark file, unchanged, on Ruby implementations; one CSV row per iteration.

usage (from ~/ruby-rpyyarv/rpyyarv):
  python3 bench/run_bench.py ../benchmark/app_answer.rb --impl rpyyarv [--rpyyarv-bin NAME]
                             [--iters 100] [--runs 10]

--rpyyarv-bin / --rpyyarv-nojit-bin pick the RPyYARV binary to measure: a path, or a bare
name looked up in ~/ruby-rpyyarv.  Every CSV row records the binary's name and the first
8 hex digits of its SHA-256, so rebuilds that keep a name stay apart.
"""
import argparse
import csv
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))   # ~/ruby-rpyyarv/rpyyarv/bench
TOP = os.path.dirname(os.path.dirname(HERE))        # ~/ruby-rpyyarv
BUILD = os.environ.get('RPYYARV_BUILD', os.path.join(TOP, 'build'))
# CRuby with YJIT and ZJIT, built from a clean clone of the same commit: ~/ruby-jit/build
JIT_BUILD = os.environ.get('RPYYARV_JIT_BUILD',
                           os.path.join(os.path.dirname(TOP), 'ruby-jit', 'build'))
RUBY_JIT = os.path.join(JIT_BUILD, 'ruby')
PRELUDE = '-r' + os.path.join(HERE, 'prelude.rb')
# Results live outside the repository: ~/rpyyarv-results
RESULTS = os.environ.get('RPYYARV_RESULTS',
                         os.path.join(os.path.dirname(TOP), 'rpyyarv-results'))

IMPL_NAMES = ['rpyyarv', 'rpyyarv-nojit', 'cruby', 'yjit', 'zjit', 'truffleruby']
HEADER = ['bench', 'impl', 'binary', 'sha', 'run', 'iter', 'ns']

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


def _find_truffleruby():
    found = sorted(glob.glob(os.path.expanduser(
        '~/.rbenv/versions/truffleruby-*/bin/truffleruby')))
    if len(found) > 1:
        sys.exit('several TruffleRubies installed; set TRUFFLERUBY_BIN:\n  ' + '\n  '.join(found))
    return found[0] if found else 'truffleruby'


def rpyyarv_path(name):
    """A path as given; a bare name is a binary in ~/ruby-rpyyarv."""
    name = os.path.expanduser(name)
    return name if os.sep in name else os.path.join(TOP, name)


def command(impl, a):
    """(argv prefix, directory of the libruby.so it must load or None) for an implementation."""
    if impl == 'rpyyarv':
        return [rpyyarv_path(a.rpyyarv_bin), '--disable-gems'], BUILD
    if impl == 'rpyyarv-nojit':
        return [rpyyarv_path(a.rpyyarv_nojit_bin), '--disable-gems'], BUILD
    # CRuby, YJIT and ZJIT share one binary so that only the JIT differs.
    if impl == 'cruby':
        return [RUBY_JIT, '--disable-gems', PRELUDE], JIT_BUILD
    if impl in ('yjit', 'zjit'):
        return [RUBY_JIT, '--' + impl, '--disable-gems', PRELUDE], JIT_BUILD
    return [os.environ.get('TRUFFLERUBY_BIN') or _find_truffleruby(),
            '--disable-gems', PRELUDE], None


def binary_id(exe):
    """(name, first 8 hex digits of the SHA-256 of the file it resolves to)."""
    real = exe if os.sep in exe else shutil.which(exe)
    if not real or not os.access(real, os.X_OK):
        sys.exit('not an executable: %s' % exe)
    h = hashlib.sha256()
    with open(os.path.realpath(real), 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return os.path.basename(exe), h.hexdigest()[:8]


def env_for(libdir):
    env = dict(os.environ)
    if libdir:
        env['LD_LIBRARY_PATH'] = os.pathsep.join(
            [libdir] + [p for p in [os.environ.get('LD_LIBRARY_PATH')] if p])
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bench')
    ap.add_argument('--impl', action='append', choices=IMPL_NAMES, required=True)
    ap.add_argument('--rpyyarv-bin', default=os.environ.get('RPYYARV_BIN', 'rpyyarv-jit'),
                    help='RPyYARV with JIT: a path, or a name in ~/ruby-rpyyarv (default rpyyarv-jit)')
    ap.add_argument('--rpyyarv-nojit-bin', default=os.environ.get('RPYYARV_NOJIT_BIN', 'rpyyarv-vm'),
                    help='RPyYARV without JIT: a path, or a name in ~/ruby-rpyyarv (default rpyyarv-vm)')
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

    new = not os.path.exists(out)
    if not new:
        with open(out) as f:
            head = next(csv.reader(f), None)
        if head != HEADER:
            sys.exit('%s has columns %s, expected %s:\nconvert it first, or pass --out NEW.csv'
                     % (out, head, HEADER))

    with open(out, 'a', newline='') as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        for impl in a.impl:
            cmd, libdir = command(impl, a)
            binary, sha = binary_id(cmd[0])
            print('%s: %s (sha256 %s...)' % (impl, cmd[0], sha))
            for run in range(a.runs):
                p = subprocess.run(cmd + [gen], env=env_for(libdir),
                                   capture_output=True, text=True)
                times = [int(l[len(MARK):]) for l in p.stdout.splitlines()
                         if l.startswith(MARK)]
                if p.returncode != 0 or len(times) != a.iters:
                    sys.exit('[%s run %d] exit=%d, %d/%d samples\n%s%s'
                             % (impl, run, p.returncode, len(times), a.iters,
                                p.stdout[-2000:], p.stderr[-2000:]))
                for i, ns in enumerate(times):
                    w.writerow([name, impl, binary, sha, run, i, ns])
                f.flush()
                s = sorted(times)
                print('%-14s %-26s run %2d  first %8.2f ms  median %8.2f ms'
                      % (impl, binary + '@' + sha, run, times[0] / 1e6, s[len(s) // 2] / 1e6))
    print('wrote', out)


if __name__ == '__main__':
    main()