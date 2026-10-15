#!/usr/bin/env python3
"""Statistics from run_bench.py's raw CSV.

usage (from ~/ruby-rpyyarv/rpyyarv):
  python3 bench/summarize.py SRC [--steady-from 50] [--steady-to N]
                             [--baseline cruby] [--baseline-sha SHA] [--no-windows-copy]
  SRC is a raw CSV, or a benchmark name for ~/ruby-rpyyarv/bench_results/raw/<name>.csv
  -> ~/ruby-rpyyarv/bench_results/<name>_by_iter.csv  per iteration, across runs
  -> ~/ruby-rpyyarv/bench_results/<name>_steady.csv   steady state, speedup over baseline
  then both, and SRC under raw/, are copied to C:\\Users\\katue\\RPYYARV研究\\bench_results

Rows are grouped by (bench, impl, binary, sha), so each build of a binary is its own group.
"""
import argparse
import collections
import csv
import math
import os
import random
import shutil
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))   # ~/ruby-rpyyarv/rpyyarv/bench
TOP = os.path.dirname(os.path.dirname(HERE))        # ~/ruby-rpyyarv
# Same default as run_bench.py: ~/ruby-rpyyarv/bench_results
RESULTS = os.environ.get('RPYYARV_RESULTS', os.path.join(TOP, 'bench_results'))
# Copy for Excel on the Windows side; set RPYYARV_WINDOWS_COPY= (empty) to turn it off
WINDOWS_COPY = os.environ.get('RPYYARV_WINDOWS_COPY',
                              '/mnt/c/Users/katue/RPYYARV研究/bench_results')

# Two-sided 95% critical values of Student's t, by degrees of freedom
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
       8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
       14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
       20: 2.086, 25: 2.060, 30: 2.042}


def t95(df):
    if df > 30:
        return 1.96
    return T95[max(k for k in T95 if k <= df)]   # missing df: next smaller, wider


def mean_ci(xs):
    """Mean and the half-width of its 95% confidence interval."""
    m = statistics.fmean(xs)
    if len(xs) < 2:
        return m, None
    return m, t95(len(xs) - 1) * statistics.stdev(xs) / math.sqrt(len(xs))


def quartiles(xs):
    if len(xs) < 2:
        return xs[0], xs[0]
    q = statistics.quantiles(xs, n=4, method='inclusive')
    return q[0], q[2]


def bootstrap_ratio(base, other, b=10000, seed=0):
    """95% CI of mean(base) / mean(other), resampling runs."""
    rnd = random.Random(seed)
    rs = sorted(statistics.fmean(rnd.choices(base, k=len(base))) /
                statistics.fmean(rnd.choices(other, k=len(other)))
                for _ in range(b))
    return rs[int(0.025 * b)], rs[int(0.975 * b) - 1]


def fmt(x):
    return '' if x is None else '%.4f' % x


def label(key):
    bench, impl, binary, sha = key
    return '%s %s@%s' % (impl, binary, sha) if binary else impl


def source_path(src):
    """A path as given; a bare benchmark name is its raw CSV under RESULTS/raw."""
    src = os.path.expanduser(src)
    if os.path.exists(src) or os.sep in src or src.endswith('.csv'):
        return src
    return os.path.join(RESULTS, 'raw', src + '.csv')


def output_paths(src):
    name = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(RESULTS, exist_ok=True)
    return (os.path.join(RESULTS, name + '_by_iter.csv'),
            os.path.join(RESULTS, name + '_steady.csv'))


def copy_to_windows(copies):
    """Copy (source, path under WINDOWS_COPY) pairs; the WSL files stay the originals."""
    if not WINDOWS_COPY:
        return
    if not os.path.isdir(os.path.dirname(WINDOWS_COPY.rstrip('/'))):
        print('\n(Windows copy skipped: %s is not reachable)' % WINDOWS_COPY)
        return
    locked = []
    for src, rel in copies:
        dst = os.path.join(WINDOWS_COPY, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            # copyfile, not copy2: drvfs may refuse the permission bits copy2 sets
            shutil.copyfile(src, dst)
        except PermissionError:
            locked.append(dst)
            continue
        print('copied', dst)
    if locked:
        # Excel locks what it has open; the results in WSL are already written
        print('\nnot copied (close them in Excel and run summarize again):\n  '
              + '\n  '.join(locked))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src', help='raw CSV from run_bench.py, or a benchmark name')
    ap.add_argument('--steady-from', type=int, default=50,
                    help='first iteration of the steady-state window (default 50)')
    ap.add_argument('--steady-to', type=int,
                    help='end of the window, exclusive (default: through the last iteration)')
    ap.add_argument('--baseline', default='cruby',
                    help='implementation the speedups are relative to (default cruby)')
    ap.add_argument('--baseline-sha',
                    help='which build of the baseline, when the CSV holds several')
    ap.add_argument('--no-windows-copy', action='store_true',
                    help='do not copy the results to the Windows side')
    a = ap.parse_args()

    src = source_path(a.src)
    if not os.path.exists(src):
        sys.exit('no such CSV: %s' % src)
    by_iter_path, steady_path = output_paths(src)

    # (bench, impl, binary, sha) -> run -> iter -> ms; CSVs without binary/sha still load
    data = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in csv.DictReader(open(src)):
        key = (r['bench'], r['impl'], r.get('binary', ''), r.get('sha', ''))
        data[key][int(r['run'])][int(r['iter'])] = int(r['ns']) / 1e6

    # 1. Per iteration, across runs (warmup curves)
    with open(by_iter_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['bench', 'impl', 'binary', 'sha', 'iter', 'runs',
                    'mean_ms', 'geomean_ms', 'median_ms', 'stdev_ms', 'min_ms', 'max_ms',
                    'q1_ms', 'q3_ms'])
        for key, runs in sorted(data.items()):
            for it in sorted(set(i for t in runs.values() for i in t)):
                xs = [t[it] for t in runs.values() if it in t]
                q1, q3 = quartiles(xs)
                w.writerow(list(key) + [it, len(xs)] +
                           [fmt(x) for x in (statistics.fmean(xs),
                                             statistics.geometric_mean(xs),
                                             statistics.median(xs),
                                             statistics.stdev(xs) if len(xs) > 1 else 0.0,
                                             min(xs), max(xs), q1, q3)])

    # 2. Steady state: arithmetic mean over the window within each run (GC included),
    #    then mean and 95% CI across runs
    def in_window(it):
        return it >= a.steady_from and (a.steady_to is None or it < a.steady_to)

    per_run, medians = {}, {}   # key -> [value of each run]
    for key, runs in sorted(data.items()):
        per_run[key], medians[key] = [], []
        for run, t in sorted(runs.items()):
            win = [ms for it, ms in t.items() if in_window(it)]
            if not win:
                sys.exit('%s run %d: no iterations in the steady window' % (label(key), run))
            per_run[key].append(statistics.fmean(win))
            medians[key].append(statistics.median(win))

    # The baseline of each benchmark must be a single build
    baseline = {}
    for bench in sorted(set(k[0] for k in per_run)):
        cands = [k for k in per_run if k[0] == bench and k[1] == a.baseline
                 and (a.baseline_sha is None or k[3] == a.baseline_sha)]
        if len(cands) > 1:
            sys.exit('%s: several %s builds; pick one with --baseline-sha:\n  %s'
                     % (bench, a.baseline, '\n  '.join(label(k) for k in cands)))
        if cands:
            baseline[bench] = cands[0]

    rows = []
    for key, xs in sorted(per_run.items()):
        m, ci = mean_ci(xs)
        sp = lo = hi = None
        bkey = baseline.get(key[0])
        if bkey is not None:
            base = per_run[bkey]
            sp = statistics.fmean(base) / m
            if key != bkey:
                lo, hi = bootstrap_ratio(base, xs)
        rows.append((key, len(xs), m, ci, statistics.fmean(medians[key]), sp, lo, hi))

    with open(steady_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['bench', 'impl', 'binary', 'sha', 'runs', 'steady_mean_ms', 'ci95_ms',
                    'steady_median_ms', 'speedup_vs_' + a.baseline, 'speedup_lo', 'speedup_hi'])
        for key, n, m, ci, med, sp, lo, hi in rows:
            w.writerow(list(key) + [n] + [fmt(x) for x in (m, ci, med, sp, lo, hi)])

    window = '%d..%s' % (a.steady_from, a.steady_to - 1 if a.steady_to else 'last')
    print('steady window: iterations %s, speedup = %s time / impl time\n' % (window, a.baseline))
    print('%-12s %-36s %10s %9s %10s %20s'
          % ('bench', 'impl binary@sha', 'mean ms', '±95%', 'median ms', 'speedup [95% CI]'))
    for key, n, m, ci, med, sp, lo, hi in rows:
        spd = '' if sp is None else '%.2fx' % sp
        if lo is not None:
            spd += ' [%.2f, %.2f]' % (lo, hi)
        print('%-12s %-36s %10.2f %9s %10.2f %20s' % (key[0], label(key), m, fmt(ci), med, spd))

    # Several benchmarks: geometric mean of the per-benchmark speedups
    by_build = collections.defaultdict(list)
    for key, n, m, ci, med, sp, lo, hi in rows:
        if sp is not None:
            by_build[key[1:]].append(sp)
    if any(len(v) > 1 for v in by_build.values()):
        print('\ngeometric mean of speedups over benchmarks:')
        for build, sps in sorted(by_build.items()):
            print('  %-36s %.2fx  (%d benchmarks)'
                  % (label(('',) + build), math.exp(statistics.fmean(math.log(s) for s in sps)),
                     len(sps)))

    if not baseline:
        print('\n(no %s rows yet: speedup columns are empty)' % a.baseline)
    print('\nwrote', by_iter_path)
    print('wrote', steady_path)

    if not a.no_windows_copy:
        copy_to_windows([(by_iter_path, os.path.basename(by_iter_path)),
                         (steady_path, os.path.basename(steady_path)),
                         (src, os.path.join('raw', os.path.basename(src)))])


if __name__ == '__main__':
    main()