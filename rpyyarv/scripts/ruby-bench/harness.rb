# Stand-in for ruby-bench's harness/harness.rb that rpyyarv can run natively.
# Mirrors upstream ruby-bench/harness/harness.rb (WARMUP_ITRS, MIN_BENCH_ITRS,
# MIN_BENCH_TIME) without the CSV/RSS/JIT-stats parts; upstream harness/loader.rb
# and harness-common.rb use constructs rpyyarv delegates. Output is the ITER/DONE
# protocol scripts/bench.rb parses for both suites.

WARMUP_ITRS = Integer(ENV.fetch('WARMUP_ITRS', '15'))
# Seconds of warmup a tracing JIT needs regardless of the iteration count; both floors apply, and warmup keeps extending while iterations still get faster, up to WARMUP_MAX.
WARMUP_TIME = Float(ENV.fetch('WARMUP_TIME', '0'))
WARMUP_MAX = Float(ENV.fetch('WARMUP_MAX', '30'))
MIN_BENCH_ITRS = Integer(ENV.fetch('MIN_BENCH_ITRS', '10'))
MIN_BENCH_TIME = Integer(ENV.fetch('MIN_BENCH_TIME', '10'))

Random.srand(1337)

# Noop stand-in for harness-common's Ractor.make_shareable; the benchmarks run in one ractor.
def make_shareable(obj, *_rest)
  obj
end

# harness-common's use_gemfile without the `bundle install` shell-out: gems must already be installed.
def use_gemfile(*_rest)
  # RubyGems and Bundler initialized the embedded CRuby before RPyYARV starts.
  # Let CRuby own their bootstrap requires, then restore interception so the
  # benchmark gem's Ruby files are compiled and executed by RPyYARV.
  previous = ENV["RPYYARV_FOREIGN_REQUIRE"]
  ENV["RPYYARV_FOREIGN_REQUIRE"] = "1"
  begin
    require "bundler"
    Bundler.setup
  ensure
    if previous
      ENV["RPYYARV_FOREIGN_REQUIRE"] = previous
    else
      ENV.delete("RPYYARV_FOREIGN_REQUIRE")
    end
  end
end

def run_benchmark(_num_itrs_hint, *_rest)
  total = 0
  measured = 0
  n = 0
  warmed = nil
  recent = []
  loop do
    t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    yield
    t1 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    ms = (t1 - t0) * 1000.0
    total += ms
    measured += ms if warmed
    puts "ITER " + n.to_s + " " + ms.to_s + " true"
    recent << ms
    recent.shift if recent.length > 10
    n += 1
    if warmed.nil? && n >= WARMUP_ITRS && total >= WARMUP_TIME * 1000
      # Warm once the last five iterations stopped improving on the five before, or the cap ran out; the driver drops everything before this point. WARMUP_TIME 0 keeps the plain iteration-count behavior.
      settled = WARMUP_TIME == 0 ||
                (recent.length >= 10 &&
                 recent[5, 5].min >= recent[0, 5].min * 0.97)
      if settled || total >= WARMUP_MAX * 1000
        warmed = n
        puts "WARMED " + n.to_s
      end
    end
    break if warmed && n - warmed >= MIN_BENCH_ITRS && measured >= MIN_BENCH_TIME * 1000
  end
  puts "DONE true"
end
