# Minimal stand-in for yjit-bench's harness/harness.rb that rpyyarv can run natively.
# Same iteration protocol (WARMUP_ITRS then MIN_BENCH_ITRS/MIN_BENCH_TIME), no CSV/RSS/JIT stats.

WARMUP_ITRS = Integer(ENV.fetch('WARMUP_ITRS', '15'))
MIN_BENCH_ITRS = Integer(ENV.fetch('MIN_BENCH_ITRS', '10'))
MIN_BENCH_TIME = Integer(ENV.fetch('MIN_BENCH_TIME', '10'))

Random.srand(1337)

# Noop stand-in for harness-common's Ractor.make_shareable; the benchmarks run in one ractor.
def make_shareable(obj, *_rest)
  obj
end

def run_benchmark(_num_itrs_hint, *_rest)
  times = []
  total = 0
  n = 0
  loop do
    t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC, :nanosecond)
    yield
    t1 = Process.clock_gettime(Process::CLOCK_MONOTONIC, :nanosecond)
    ms = (t1 - t0) / 1000000.0
    n += 1
    times << ms
    total += ms
    puts "itr #{n}: #{ms.round(3)}ms"
    break if n >= WARMUP_ITRS + MIN_BENCH_ITRS && total >= MIN_BENCH_TIME * 1000
  end
  bench = times[WARMUP_ITRS..-1]
  sorted = bench.sort
  mid = sorted.length / 2
  median = sorted.length % 2 == 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2.0
  puts "RESULT median_ms #{median.round(3)} n #{bench.length} min #{sorted[0].round(3)}"
end
