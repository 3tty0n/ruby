#!/usr/bin/env python3
"""Statistics from run_bench.py's raw CSV.

usage: python3 bench/summarize.py SRC.csv [--steady-from 50] [--steady-to N] [--baseline cruby]
  -> C:\\Users\\katue\\RPYYARV研究\\bench_results\\<name>_by_iter.csv  per iteration, across runs
  -> C:\\Users\\katue\\RPYYARV研究\\bench_results\\<name>_steady.csv   steady state, speedup over baseline
"""
import argparse
import collections
import csv
import math
import os
import random
import statistics
import sys

# Windows side, seen from WSL: C:\Users\katue\RPYYARV研究\bench_results
OUT_DIR = os.environ.get('RPYYARV_BENCH_RESULTS',
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


def output_paths(src):
    name = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(OUT_DIR, exist_ok=True)
    return (os.path.join(OUT_DIR, name + '_by_iter.csv'),
            os.path.join(OUT_DIR, name + '_steady.csv'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--steady-from', type=int, default=50,
                    help='first iteration of the steady-state window (default 50)')
    ap.add_argument('--steady-to', type=int,
                    help='end of the window, exclusive (default: through the last iteration)')
    ap.add_argument('--baseline', default='cruby',
                    help='implementation the speedups are relative to (default cruby)')
    a = ap.parse_args()

    src = os.path.expanduser(a.src)
    by_iter_path, steady_path = output_paths(src)

    # (bench, impl) -> run -> iter -> ms
    data = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in csv.DictReader(open(src)):
        data[(r['bench'], r['impl'])][int(r['run'])][int(r['iter'])] = int(r['ns']) / 1e6

    # 1. Per iteration, across runs (warmup curves)
    with open(by_iter_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['bench', 'impl', 'iter', 'runs',
                    'mean_ms', 'geomean_ms', 'median_ms', 'stdev_ms', 'min_ms', 'max_ms',
                    'q1_ms', 'q3_ms'])
        for (bench, impl), runs in sorted(data.items()):
            for it in sorted(set(i for t in runs.values() for i in t)):
                xs = [t[it] for t in runs.values() if it in t]
                q1, q3 = quartiles(xs)
                w.writerow([bench, impl, it, len(xs)] +
                           [fmt(x) for x in (statistics.fmean(xs),
                                             statistics.geometric_mean(xs),
                                             statistics.median(xs),
                                             statistics.stdev(xs) if len(xs) > 1 else 0.0,
                                             min(xs), max(xs), q1, q3)])

    # 2. Steady state: arithmetic mean over the window within each run (GC included),
    #    then mean and 95% CI across runs
    def in_window(it):
        return it >= a.steady_from and (a.steady_to is None or it < a.steady_to)

    per_run, medians = {}, {}   # (bench, impl) -> [value of each run]
    for (bench, impl), runs in sorted(data.items()):
        per_run[(bench, impl)], medians[(bench, impl)] = [], []
        for run, t in sorted(runs.items()):
            win = [ms for it, ms in t.items() if in_window(it)]
            if not win:
                sys.exit('%s/%s run %d: no iterations in the steady window' % (bench, impl, run))
            per_run[(bench, impl)].append(statistics.fmean(win))
            medians[(bench, impl)].append(statistics.median(win))

    rows = []
    for (bench, impl), xs in sorted(per_run.items()):
        m, ci = mean_ci(xs)
        base = per_run.get((bench, a.baseline))
        sp = lo = hi = None
        if base is not None:
            sp = statistics.fmean(base) / m
            if impl != a.baseline:
                lo, hi = bootstrap_ratio(base, xs)
        rows.append((bench, impl, len(xs), m, ci,
                     statistics.fmean(medians[(bench, impl)]), sp, lo, hi))

    with open(steady_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['bench', 'impl', 'runs', 'steady_mean_ms', 'ci95_ms',
                    'steady_median_ms', 'speedup_vs_' + a.baseline, 'speedup_lo', 'speedup_hi'])
        for r in rows:
            w.writerow(list(r[:3]) + [fmt(x) for x in r[3:]])

    window = '%d..%s' % (a.steady_from, a.steady_to - 1 if a.steady_to else 'last')
    print('steady window: iterations %s, speedup = %s time / impl time\n' % (window, a.baseline))
    print('%-12s %-12s %12s %10s %12s %20s'
          % ('bench', 'impl', 'mean ms', '±95%', 'median ms', 'speedup [95% CI]'))
    for bench, impl, n, m, ci, med, sp, lo, hi in rows:
        spd = '' if sp is None else '%.2fx' % sp
        if lo is not None:
            spd += ' [%.2f, %.2f]' % (lo, hi)
        print('%-12s %-12s %12.2f %10s %12.2f %20s' % (bench, impl, m, fmt(ci), med, spd))

    # Several benchmarks: geometric mean of the per-benchmark speedups
    by_impl = collections.defaultdict(list)
    for bench, impl, n, m, ci, med, sp, lo, hi in rows:
        if sp is not None:
            by_impl[impl].append(sp)
    if any(len(v) > 1 for v in by_impl.values()):
        print('\ngeometric mean of speedups over benchmarks:')
        for impl, sps in sorted(by_impl.items()):
            print('  %-12s %.2fx  (%d benchmarks)'
                  % (impl, math.exp(statistics.fmean(math.log(s) for s in sps)), len(sps)))

    if not any(impl == a.baseline for _, impl in per_run):
        print('\n(no %s rows yet: speedup columns are empty)' % a.baseline)
    print('\nwrote', by_iter_path)
    print('wrote', steady_path)


if __name__ == '__main__':
    main()