#!/usr/bin/env python3
"""Per-iteration statistics across runs, from run_bench.py's raw CSV.

usage: python3 bench/summarize.py ~/rpyyarv-results/app_answer.csv
  -> writes ~/rpyyarv-results/app_answer_by_iter.csv
"""
import collections
import csv
import os
import statistics
import sys

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + '_by_iter.csv'

groups = collections.defaultdict(list)          # (bench, impl, iter) -> [ms, ...]
for r in csv.DictReader(open(src)):
    groups[(r['bench'], r['impl'], int(r['iter']))].append(int(r['ns']) / 1e6)

with open(dst, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['bench', 'impl', 'iter', 'runs',
                'mean_ms', 'geomean_ms', 'median_ms', 'stdev_ms', 'min_ms', 'max_ms'])
    for (bench, impl, it), xs in sorted(groups.items()):
        w.writerow([bench, impl, it, len(xs),
                    '%.4f' % statistics.fmean(xs),
                    '%.4f' % statistics.geometric_mean(xs),
                    '%.4f' % statistics.median(xs),
                    '%.4f' % (statistics.stdev(xs) if len(xs) > 1 else 0.0),
                    '%.4f' % min(xs),
                    '%.4f' % max(xs)])
print('wrote', dst)