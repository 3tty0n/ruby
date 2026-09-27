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

Dir.mktmpdir("rpyyarv-warmup-test") do |dir|
  steady = [4.0] * 6
  raw = {
    # flat, warmup, slowdown, and never stable, one process each.
    "awfy/a/rpyyarv-jit" => { "raw_iterations" => [steady],
                              "warmed_at" => [0] },
    "awfy/b/rpyyarv-jit" => { "raw_iterations" => [[40.0] + steady],
                              "warmed_at" => [1] },
    "awfy/c/rpyyarv-jit" => { "raw_iterations" => [[1.0] + steady],
                              "warmed_at" => [1] },
    "awfy/d/rpyyarv-jit" => {
      "raw_iterations" => [[1.0, 9.0, 1.0, 9.0, 1.0, 9.0]],
      "warmed_at" => [0]
    },
    "awfy/b/cruby+yjit" => { "raw_iterations" => [[10.0] + [2.0] * 6],
                             "warmed_at" => [1] }
  }
  File.write(File.join(dir, "raw.json"), JSON.generate(raw))
  assert(RPyYARVEvaluation::Analyzer.warmup_only(dir) == 5, "warmup rows")
  rows = File.readlines(File.join(dir, "warmup-summary.csv"), chomp: true)
  head = rows.first.split(",")
  jit = rows.find { |line| line.start_with?("all,rpyyarv-jit") }.split(",")
  cell = ->(name) { jit[head.index(name)] }
  assert(cell.call("processes") == "4", "process count")
  assert(cell.call("processes_stable") == "3", "stable process count")
  assert(cell.call("flat") == "1" && cell.call("warmup") == "1" &&
         cell.call("slowdown") == "1" && cell.call("no_steady_state") == "1",
         "Barrett categories")
  assert(cell.call("median_time_to_stable_ms") == "5.0", "median time")
  comparison = File.readlines(File.join(dir, "warmup-comparison.csv"),
                              chomp: true)
  b = comparison.find { |line| line.start_with?("b,") }.split(",")
  assert(b[1] == "44.0" && b[2] == "12.0", "per-benchmark medians")
  assert(b[3].to_f.round(4) == (44.0 / 12.0).round(4), "time ratio")
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

Dir.mktmpdir("rpyyarv-figures-test") do |dir|
  source = File.join(dir, "20260101T000000Z-performance-1")
  FileUtils.mkdir_p(source)
  File.write(File.join(source, "manifest.json"),
             JSON.generate("kind" => "performance", "git" => { "commit" => "a" },
                           "engine_binaries" => { "rpyyarv-jit" =>
                                                    { "sha256" => "b" } }))
  File.write(File.join(source, "measurements.csv"), <<~CSV)
    suite,benchmark,engine,median_ms,files_native,files_delegated
    awfy,bounce,cruby,10.0,1,0
    awfy,bounce,cruby+yjit,5.0,1,0
    awfy,bounce,rpyyarv,20.0,1,0
    awfy,bounce,rpyyarv-jit,4.0,1,0
  CSV
  File.write(File.join(source, "raw.json"), JSON.generate(
    "awfy/bounce/cruby" => { "raw_iterations" => [[3.0, 2.0, 2.0]],
                             "warmed_at" => [1] },
    "awfy/bounce/rpyyarv-jit" => { "raw_iterations" => [[9.0, 4.0, 4.0]],
                                   "warmed_at" => [1] }
  ))
  out = File.join(dir, "figures")
  rendered = RPyYARVEvaluation::Figures.render([source], out)
  names = rendered.map { |figure| figure["name"] }
  assert(names.include?("peak-performance"), "peak figure rendered")
  assert(File.read(File.join(out, "peak-vs-cruby.svg")).include?("bounce"),
         "peak figure benchmark label")
  manifest = JSON.parse(File.read(File.join(out, "manifest.json")))
  assert(manifest["inputs"][0]["git_commit"] == "a", "input commit recorded")
  assert(manifest["skipped"].key?("memory"), "absent kind is skipped")
end

require_relative "../scripts/bench_viz"

Dir.mktmpdir("rpyyarv-jsonl-viz-test") do |dir|
  jsonl = File.join(dir, "bench.jsonl")
  File.open(jsonl, "w") do |file|
    2.times do |i|
      raw = {
        "awfy/bounce/cruby+yjit" => { "median" => 5.0 },
        "awfy/bounce/rpyyarv-jit" => { "median" => 4.0 + i }
      }
      file.puts(JSON.generate("ts" => "2026-01-0#{i + 1}T00:00:00Z",
                              "commit" => "abc", "raw" => raw))
    end
  end
  out = File.join(dir, "viz")
  paths = viz(jsonl, out)
  assert(paths.any? { |path| File.basename(path) == "history.svg" }, "history svg")
  assert(File.read(File.join(out, "history.svg")).include?("polyline"),
         "history series")
  assert(paths.any? { |path| File.basename(path).start_with?("ratio-") },
         "latest ratio plot")
end

boot = RPyYARVEvaluation::Bootstrap
lo, hi = boot.geomean_ci([[[4.0, 4.0], [8.0, 8.0]]], resamples: 100)
assert(lo == 0.5 && hi == 0.5, "constant samples give a point interval")
lo, hi = boot.geomean_ci([[[1.0, 2.0, 3.0], [2.0]], [[8.0], [2.0]]],
                         resamples: 1000)
assert(lo < 1.0 && hi > 2.0 && hi <= 4.0, "interval spans both benchmarks")

require_relative "correlations"
rows = (1..6).map do |i|
  { "cruby_sends_per_iteration" => i * i, "bridges_per_loop" => 7 - i,
    "performance_jit_over_yjit" => Math.exp(Math.log1p(i * i)) }
end
corr = Correlations.analyze(rows)
                   .to_h { |r| [[r["predictor"], r["method"]], r] }
assert(corr[["cruby_sends_per_iteration", "pearson"]]["r"].round(9) == 1.0,
       "log-log pearson")
assert(corr[["bridges_per_loop", "spearman"]]["r"].round(9) == -1.0,
       "spearman ranks")

require_relative "footprint"
require_relative "retention"

Dir.mktmpdir("rpyyarv-footprint-test") do |dir|
  row = ->(t, a, b, d, detail = "") do
    format("%-26s %x-%x [ 1M 1M %s 0K] rw-/rwx SM=PRV  %s\n", t, a, b, d,
           detail)
  end
  vm = Footprint.parse_vmmap(
    "Physical footprint:         7.5M\n" +
    row["MALLOC_LARGE", 0x1000, 0x2000, "4096K"] +
    row["VM_ALLOCATE", 0x3000, 0x4000, "2048K"] +
    row["VM_ALLOCATE", 0x5000, 0x6000, "1024K"] +
    row["__DATA", 0x7000, 0x8000, "512K", "/x/rpyyarv-jit"])
  st = { "heap_page_bytes" => 1_048_576, "yjit_code_region_size" => 0,
         "yjit_alloc_size" => 0 }
  py = Footprint.parse_pypylog(
    "nursery size: 1048576\nminor collect, total memory used: 524288\n" \
    "Loop 1 has address 0x5100 to 0x5200\n")
  c = Footprint.attribute(vm, st, py, "/x/rpyyarv-jit")
  assert(c.values.sum == vm[:footprint], "components sum to the footprint")
  assert(c["jit_code"] == 1_048_576 && c["cruby_heap"] == 1_048_576,
         "jit region and host pages")
  assert(c["rpython_heap"] == 1_572_864 && c["image_self"] == 524_288,
         "framework heap and binary data")
  File.write(File.join(dir, "t.msl"), <<~TREE)
        9 (3.00M) << TOTAL >>
          5 (2.00M) malloc  (in libsystem_malloc.dylib) + 0
          + 3 (1.50M) pypy_g_ArenaCollection_x  (in rpyyarv-jit) + 1
          + ! 3 (1.50M) rb_foo  (in libruby.4.0.dylib) + 1
          + 2 (512K) objspace_xmalloc0  (in libruby.4.0.dylib) + 1
          4 (1.00M) pypy_g_alloc_1  (in rpyyarv-jit) + 1
  TREE
  m = Footprint.msl_classes(File.join(dir, "t.msl"))
  assert(m == { "rpython_heap" => 1_572_864, "cruby_malloc" => 524_288,
                "jit_code" => 1_048_576 }, "allocation sites by image")

  dump = File.join(dir, "heap.json")
  objs = [
    { "type" => "ROOT", "root" => "vm", "references" => %w[0x1 0x2] },
    { "address" => "0x1", "type" => "DATA",
      "struct" => "rpyyarv/gc_mark_hook", "references" => %w[0x3 0x5] },
    { "address" => "0x2", "type" => "OBJECT", "memsize" => 40 },
    { "address" => "0x3", "type" => "CLASS", "singleton" => true,
      "references" => %w[0x4], "memsize" => 100 },
    { "address" => "0x4", "type" => "OBJECT", "memsize" => 40 },
    { "address" => "0x5", "type" => "OBJECT", "references" => %w[0x2],
      "memsize" => 40 }
  ]
  File.write(dump, objs.map { JSON.generate(_1) }.join("\n"))
  r = Retention.analyse(dump, { pinned: "0", classes: "1", held: "0",
                                forever: "0" })
  sets = r["sets"]
  assert(sets["hook:classes/singleton"]["retained_bytes"] == 140,
         "singleton class and its attached object")
  assert(sets["hook:pools+caches+frames"]["retained"] == 1,
         "an object a CRuby root also reaches is not retained")
  assert(r["rpyyarv_only"] == 3, "rpyyarv-only objects")
end

puts "evaluation tests: ok"
