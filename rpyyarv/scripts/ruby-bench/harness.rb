# frozen_string_literal: true
#
# Stand-in for ruby-bench's harness/harness.rb that rpyyarv can run natively.
# Mirrors upstream ruby-bench/harness/harness.rb (WARMUP_ITRS, MIN_BENCH_ITRS,
# MIN_BENCH_TIME) without the CSV/RSS/JIT-stats parts; upstream harness/loader.rb
# and harness-common.rb use constructs rpyyarv punts on. Output is the ITER/DONE
# protocol scripts/bench.rb parses for both suites.

WARMUP_ITRS = Integer(ENV.fetch('WARMUP_ITRS', '15'))
MIN_BENCH_ITRS = Integer(ENV.fetch('MIN_BENCH_ITRS', '10'))
MIN_BENCH_TIME = Integer(ENV.fetch('MIN_BENCH_TIME', '10'))

Random.srand(1337)

# Noop stand-in for harness-common's Ractor.make_shareable; the benchmarks run in one ractor.
def make_shareable(obj, *_rest)
  obj
end

# harness-common's use_gemfile without the `bundle install` shell-out: gems must already be installed.
def use_gemfile(*_rest)
  require "bundler"
  Bundler.setup
end

def run_benchmark(_num_itrs_hint, *_rest)
  total = 0
  n = 0
  loop do
    t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    yield
    t1 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    ms = (t1 - t0) * 1000.0
    total += ms
    puts "ITER " + n.to_s + " " + ms.to_s + " true"
    n += 1
    break if n >= WARMUP_ITRS + MIN_BENCH_ITRS && total >= MIN_BENCH_TIME * 1000
  end
  puts "DONE true"
end
