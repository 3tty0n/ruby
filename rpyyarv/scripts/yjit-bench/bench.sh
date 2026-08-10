#!/bin/sh
# Steady-state timing for the yjit-bench benchmarks that rpyyarv runs natively.
# 3 processes per engine; each prints the median of its post-warmup iterations.
S=/private/tmp/claude-501/-Users-yizawa-src-github-com-3tty0n-ruby-rpyyarv/6cc8f810-eb5c-4004-a459-b8a6c01914e2/scratchpad
YB=$S/yjit-bench
OUT=$S/timings.tsv
: > $OUT
export WARMUP_ITRS=5
export MIN_BENCH_ITRS=5
export MIN_BENCH_TIME=0
mkdir -p $S/blogs
for name in `grep '^NATIVE' $S/inventory.txt | cut -f2`; do
  f=$YB/benchmarks/$name.rb
  [ -f "$f" ] || f=$YB/benchmarks/$name/benchmark.rb
  for eng in rpyyarv-jit rpyyarv cruby yjit; do
    for p in 1 2 3; do
      log=$S/blogs/$name.$eng.$p.log
      perl -e 'alarm shift; exec @ARGV' 300 $S/run1.sh $eng $f > $log 2>&1
      rc=$?
      med=`grep -m1 'RESULT median_ms' $log | awk '{print $3}'`
      punt=`grep -c 'punted to cruby: ' $log`
      [ -n "$med" ] || med=FAIL
      [ "$punt" = "0" ] || med=PUNT
      printf '%s\t%s\t%s\t%s\n' "$name" "$eng" "$p" "$med" >> $OUT
    done
    printf '%s %s done\n' "$name" "$eng"
  done
done
