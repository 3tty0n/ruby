#!/bin/sh
# Classify every yjit-bench benchmark under ./rpyyarv (interpreter): native / punt / crash / gems.
S=/private/tmp/claude-501/-Users-yizawa-src-github-com-3tty0n-ruby-rpyyarv/6cc8f810-eb5c-4004-a459-b8a6c01914e2/scratchpad
YB=$S/yjit-bench
OUT=$S/inventory.txt
: > $OUT
export WARMUP_ITRS=0
export MIN_BENCH_ITRS=1
export MIN_BENCH_TIME=0
for f in $YB/benchmarks/*.rb $YB/benchmarks/*/benchmark.rb; do
  name=`basename $f .rb`
  case "$f" in */benchmark.rb) name=`basename \`dirname $f\`` ;; esac
  gems=no
  [ -f "`dirname $f`/Gemfile" ] && gems=yes
  log=$S/logs/$name.log
  mkdir -p $S/logs
  perl -e 'alarm shift; exec @ARGV' 90 $S/run1.sh rpyyarv $f > $log 2>&1
  rc=$?
  punt=`grep -m1 'punted to cruby: ' $log | sed 's/.*punted to cruby: //'`
  if grep -q 'RESULT median_ms' $log; then
    if [ -n "$punt" ]; then status=PUNT; else status=NATIVE; fi
  else
    status=CRASH
    [ $rc -eq 142 ] || [ $rc -eq 14 ] && status=TIMEOUT
  fi
  err=`grep -v 'not loaded' $log | grep -m1 -E 'Error|error|Exception|\[rpyyarv\] Ruby|undefined' | cut -c1-120`
  printf '%s\t%s\tgems=%s\trc=%s\t%s\t%s\n' "$status" "$name" "$gems" "$rc" "$punt" "$err" >> $OUT
  printf '%s %s\n' "$status" "$name"
done
