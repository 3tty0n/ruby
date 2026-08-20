# frozen_string_literal: true

require "json"
require "tmpdir"

require_relative "run"

def assert(condition, message)
  raise message unless condition
end

Dir.mktmpdir("rpyyarv-evaluation-test") do |dir|
  raw = {
    "awfy/bounce/cruby" => { "median" => 10.0 },
    "awfy/bounce/cruby+yjit" => { "median" => 5.0 },
    "awfy/bounce/rpyyarv-jit" => {
      "median" => 4.0,
      "info" => { "files_native" => 1, "files_delegated" => 0 }
    },
    "ruby-bench/x/rpyyarv-jit" => { "status" => "FAIL" }
  }
  raw_path = File.join(dir, "raw.json")
  File.write(raw_path, JSON.generate(raw))
  result = RPyYARVEvaluation::Analyzer.analyze(raw_path, dir)
  ratios = File.readlines(File.join(dir, "ratios.csv"), chomp: true)
  assert(result["measurements"] == 4, "measurement count")
  assert(ratios.size == 2, "failed rows must not become ratios")
  yjit_column = ratios[0].split(",").index("rpyyarv_jit_over_yjit")
  assert(ratios[1].split(",")[yjit_column].to_f == 0.8, "YJIT ratio")

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

puts "evaluation tests: ok"
