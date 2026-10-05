# frozen_string_literal: true

# GC and compaction stresses over the benchmark corpus: one process of the
# timed protocol, verified, per benchmark, stress and engine; CRuby runs
# the stresses it can take, as the oracle.
module Stress
  ROOT = File.expand_path("..", __dir__)
  # name => [env, whether stock CRuby can run it]
  STRESSES = {
    "none" => [{}, true],
    "a-autocompact" => [
      { "RUBYOPT" => "-r#{ROOT}/test/autocompact.rb",
        "RUBY_GC_HEAP_OLDOBJECT_LIMIT_FACTOR" => "0.01" }, true
    ],
    "b-dispatch-compact" => [
      { "RPYYARV_GC_STRESS" => "compact",
        "RPYYARV_GC_STRESS_EVERY" => "4096" }, false
    ],
    "c-timer-compact" => [
      { "RUBYOPT" => "-r#{ROOT}/test/compact_prelude.rb" }, true
    ],
    "d-dispatch-full" => [
      { "RPYYARV_GC_STRESS" => "1", "RPYYARV_GC_STRESS_EVERY" => "4096" },
      false
    ]
  }.freeze
  FIELDS = %w[stress suite benchmark engine outcome signature seconds].freeze

  module_function

  def engines(build)
    { "cruby" => [File.join(build, "ruby"), "--disable-gems"],
      "rpyyarv" => [File.join(ROOT, "rpyyarv")],
      "rpyyarv-jit" => [File.join(ROOT, "rpyyarv-jit")] }
  end

  # The first line that names the failure, else the harness's reason.
  def signature(info)
    text = %w[err_head err_tail out_tail].map { |k| info[k].to_s }.join("\n")
    line = text.lines.find { |l| l =~ /\[BUG\]|Error\b|terminated object/ }
    drv = %r{\A\S*/(bench|awfy)_tmp_drv_\S+: }
    (line || info["why"]).to_s.strip.sub(drv, "")[0, 160]
  end

  def one(suite, bench, stress, engine, argv, timeout)
    env_extra = STRESSES.fetch(stress)[0]
    row = nil
    suite.with_script(bench) do |script, env, _warm|
      began = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      _t, err, info = run_once(argv, script, env.merge(env_extra), timeout)
      secs = Process.clock_gettime(Process::CLOCK_MONOTONIC) - began
      # A run that outlived its alarm was killed from outside: a hang.
      err = "TIMEOUT" if err && secs >= timeout
      row = { "stress" => stress, "suite" => suite.name, "benchmark" => bench,
              "engine" => engine,
              "outcome" => err.nil? ? "pass" : err.downcase,
              "signature" => err && signature(info),
              "seconds" => secs.round(1) }
    end
    row
  end

  # Benchmarks run in parallel; one benchmark's runs stay on one thread,
  # since its generated driver file is named by benchmark and pid.
  def run(build, stresses, timeout, jobs, out_csv)
    load File.join(ROOT, "scripts", "bench.rb") unless defined?(AwfySuite)
    suites = [AwfySuite.new({}), RubyBenchSuite.new({})].select(&:available?)
    queue = suites.flat_map { |s| s.benchmarks.map { |b| [s, b] } }
    rows = []
    lock = Mutex.new
    File.open(out_csv, "w") do |csv|
      csv.puts FIELDS.join(",")
      Array.new(jobs) do
        Thread.new do
          while (item = lock.synchronize { queue.shift })
            suite, bench = item
            stresses.product(engines(build).to_a).each do |stress, (e, argv)|
              next if e == "cruby" && !STRESSES.fetch(stress)[1]

              row = one(suite, bench, stress, e, argv, timeout)
              lock.synchronize do
                rows << row
                csv.puts FIELDS.map { |k| RPyYARVEvaluation::Csv.quote(row[k]) }
                               .join(",")
                csv.flush
                puts FIELDS.map { |k| row[k] }.join("  ")
              end
            end
          end
        end
      end.each(&:join)
    end
    rows
  end

  def summarize(rows)
    rows.group_by { |r| [r["stress"], r["engine"]] }.sort.map do |(s, e), g|
      count = ->(o) { g.count { |r| r["outcome"] == o } }
      { "stress" => s, "engine" => e, "runs" => g.size,
        "pass" => count["pass"], "fail" => count["fail"],
        "timeout" => count["timeout"], "delegated" => count["delegated"] }
    end
  end
end
