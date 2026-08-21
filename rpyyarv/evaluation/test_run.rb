# frozen_string_literal: true

require "json"
require "tmpdir"

require_relative "run"
require_relative "mechanisms"

def assert(condition, message)
  raise message unless condition
end

Dir.mktmpdir("rpyyarv-evaluation-test") do |dir|
  raw = {
    "awfy/bounce/cruby" => { "median" => 10.0 },
    "awfy/bounce/cruby+yjit" => { "median" => 5.0 },
    "awfy/bounce/rpyyarv-jit" => {
      "median" => 4.0,
      "raw_iterations" => [[10.0, 8.0, 4.0, 4.1, 4.0, 4.1, 4.0]],
      "warmed_at" => [2],
      "info" => { "files_native" => 1, "files_delegated" => 0 }
    },
    "awfy/bounce/value-residual" => { "median" => 8.0 },
    "ruby-bench/x/rpyyarv-jit" => { "status" => "FAIL" }
  }
  raw_path = File.join(dir, "raw.json")
  File.write(raw_path, JSON.generate(raw))
  result = RPyYARVEvaluation::Analyzer.analyze(raw_path, dir)
  ratios = File.readlines(File.join(dir, "ratios.csv"), chomp: true)
  assert(result["measurements"] == 5, "measurement count")
  assert(result["warmup_processes"] == 1, "warmup process count")
  assert(ratios.size == 2, "failed rows must not become ratios")
  yjit_column = ratios[0].split(",").index("rpyyarv_jit_over_yjit")
  assert(ratios[1].split(",")[yjit_column].to_f == 0.8, "YJIT ratio")
  comparisons = File.read(File.join(dir, "comparisons.csv"))
  assert(comparisons.include?("value-residual,2.0"), "ablation ratio")

  plots = RPyYARVEvaluation::Plotter.plot(raw_path, dir)
  assert(plots.all? { |path| File.exist?(path) }, "plot files")
  assert(File.read(plots[0]).include?("bounce"), "ratio plot benchmark")

  log = File.join(dir, "boundary.log")
  File.write(log, "bounce sends: rpyyarv 90, cruby 10\nnoise\n")
  count = RPyYARVEvaluation::Boundary.extract(
    log, File.join(dir, "boundary.csv")
  )
  assert(count == 1, "boundary row count")
end

summary = <<~TEXT
  Tracing:         10       4.0
  Backend:         8        1.0
  TOTAL:                    20.0
  recorded ops:             100
    calls:                  20
  opt ops:                  80
  opt guards:               16
  abort: vable escape:      2
  Total # of loops:         4
  Total # of bridges:       40
  Freed # of loops:         1
  Freed # of bridges:       10
  Loop 1 (x) has address 0x1000 to 0x1100 (bootstrap 0x0)
  bridge out of Guard 0x1 has address 0x2000 to 0x2040
TEXT
metrics = MechanismHarness.parse_summary(summary)
assert(metrics["bridges_per_loop"] == 10.0, "bridge density")
assert(metrics["compile_fraction"] == 0.25, "compile fraction")
assert(metrics["residual_calls_per_opt_op"] == 0.25, "call density")
assert(metrics["compiled_trace_body_bytes"] == 320, "trace body bytes")

vm = MechanismHarness.parse_vm_stats(<<~TEXT, "yjit")
  ratio_in_yjit: 80.0
  side_exit_count: 20,000
  total_insns_count: 100000
  compiled_block_count: 60
  compiled_blockid_count: 40
TEXT
assert(vm["yjit_ratio_in_jit"] == 0.8, "JIT residency normalization")
assert(vm["yjit_side_exits_per_kinstruction"] == 200.0, "exit density")
assert(vm["yjit_versions_per_block"] == 1.5, "LBBV version density")

Dir.mktmpdir("rpyyarv-mechanism-plot-test") do |dir|
  path = File.join(dir, "mechanisms.json")
  rows = [
    { "suite" => "awfy", "benchmark" => "bounce",
      "bridges_per_loop" => 2.0, "cruby_sends_per_iteration" => 10,
      "compile_fraction" => 0.25,
      "performance_jit_over_yjit" => 0.8 }
  ]
  File.write(path, JSON.generate(rows))
  plots = RPyYARVEvaluation::Plotter.plot_mechanisms(path, dir)
  assert(plots.size == 3, "mechanism plot count")
end

puts "evaluation tests: ok"
