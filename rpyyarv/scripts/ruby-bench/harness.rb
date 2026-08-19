# Stand-in harness: upstream loader.rb uses constructs rpyyarv delegates.
# Output is the ITER/DONE protocol scripts/bench.rb parses.

WARMUP_ITRS = Integer(ENV.fetch('WARMUP_ITRS', '15'))
# Seconds of warmup a tracing JIT needs; both floors apply, up to WARMUP_MAX.
WARMUP_TIME = Float(ENV.fetch('WARMUP_TIME', '0'))
# 60: rubyboy's re-trace burst ends near iteration 17; 30 capped it mid-burst.
WARMUP_MAX = Float(ENV.fetch('WARMUP_MAX', '60'))
MIN_BENCH_ITRS = Integer(ENV.fetch('MIN_BENCH_ITRS', '10'))
MIN_BENCH_TIME = Integer(ENV.fetch('MIN_BENCH_TIME', '10'))

Random.srand(1337)

# Noop stand-in for Ractor.make_shareable; benchmarks run in one ractor.
def make_shareable(obj, *_rest)
  obj
end

# use_gemfile without the `bundle install` shell-out: gems must be installed.
def use_gemfile(*_rest)
  # CRuby owns RubyGems/Bundler bootstrap; restore interception for gem files.
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

# ractor_args mirrors upstream's non-ractor mode: yield(0, *args), whole list.
def run_benchmark(_num_itrs_hint, *_rest, ractor_args: [])
  total = 0
  measured = 0
  n = 0
  warmed = nil
  recent = []
  loop do
    t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    yield(0, *ractor_args)
    t1 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    ms = (t1 - t0) * 1000.0
    total += ms
    measured += ms if warmed
    puts "ITER " + n.to_s + " " + ms.to_s + " true"
    recent << ms
    recent.shift if recent.length > 10
    n += 1
    if warmed.nil? && n >= WARMUP_ITRS && total >= WARMUP_TIME * 1000
      # Warm when the last five stop improving AND contain no spike.
      # WARMUP_TIME 0 keeps the plain iteration-count behavior.
      settled = WARMUP_TIME == 0 ||
                (recent.length >= 10 &&
                 recent[5, 5].min >= recent[0, 5].min * 0.97 &&
                 recent[5, 5].max <= recent[5, 5].min * 1.2)
      if settled || total >= WARMUP_MAX * 1000
        warmed = n
        puts "WARMED " + n.to_s
      end
    end
    break if warmed && n - warmed >= MIN_BENCH_ITRS && measured >= MIN_BENCH_TIME * 1000
  end
  puts "DONE true"
end
