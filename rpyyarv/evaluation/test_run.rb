# frozen_string_literal: true

require "json"
require "tmpdir"

require_relative "run"
require_relative "mechanisms"
require_relative "ae"

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
                             "warmed_at" => [1] },
    # ruby-bench has its own unrelated "b", same name as awfy's above.
    "ruby-bench/b/rpyyarv-jit" => { "raw_iterations" => [[80.0] + steady],
                                    "warmed_at" => [1] },
    "ruby-bench/b/cruby+yjit" => { "raw_iterations" => [[20.0] + [2.0] * 6],
                                   "warmed_at" => [1] }
  }
  File.write(File.join(dir, "raw.json"), JSON.generate(raw))
  assert(RPyYARVEvaluation::Analyzer.warmup_only(dir) == 7, "warmup rows")
  rows = File.readlines(File.join(dir, "warmup-summary.csv"), chomp: true)
  head = rows.first.split(",")
  jit = rows.find { |line| line.start_with?("all,rpyyarv-jit") }.split(",")
  cell = ->(name) { jit[head.index(name)] }
  assert(cell.call("processes") == "5", "process count")
  assert(cell.call("flat") == "1" && cell.call("warmup") == "2" &&
         cell.call("slowdown") == "1" && cell.call("no_steady_state") == "1",
         "Barrett categories")
  assert(cell.call("median_time_to_stable_ms") == "24.5", "median time")
  comparison = File.readlines(File.join(dir, "warmup-comparison.csv"),
                              chomp: true)
  awfy_b = comparison.find { |line| line.start_with?("awfy,b,") }.split(",")
  rb_b = comparison.find { |line| line.start_with?("ruby-bench,b,") }
                   .split(",")
  assert(awfy_b[2] == "44.0" && awfy_b[3] == "12.0", "awfy b medians")
  assert(rb_b[2] == "84.0" && rb_b[3] == "22.0", "ruby-bench b medians")
  assert(awfy_b[4].to_f.round(4) == (44.0 / 12.0).round(4), "awfy b ratio")
  assert(rb_b[4].to_f.round(4) == (84.0 / 22.0).round(4), "ruby-bench b ratio")
  assert(awfy_b[4] != rb_b[4],
         "same-named benchmarks in different suites don't collide")
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

Dir.mktmpdir("rpyyarv-correlations-warmup-test") do |dir|
  # AWFY's and ruby-bench's "nbody" must not collide once keyed by suite.
  File.write(File.join(dir, "warmup-comparison.csv"), <<~CSV)
    suite,benchmark,time_to_stable_ratio
    awfy,nbody,2.0
    ruby-bench,nbody,0.5
  CSV
  ratios = Correlations.warmup_ratios(dir)
  assert(ratios[%w[awfy nbody]] == 2.0 && ratios[%w[ruby-bench nbody]] == 0.5,
         "suite-keyed warmup ratios keep same-named benchmarks distinct")
end

Dir.mktmpdir("rpyyarv-correlations-warmup-fallback-test") do |dir|
  File.write(File.join(dir, "warmup-comparison.csv"), <<~CSV)
    benchmark,time_to_stable_ratio
    nbody,2.0
  CSV
  assert(Correlations.warmup_ratios(dir) == { "nbody" => 2.0 },
         "name-keyed fallback for CSVs without a suite column")
end

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

# The paper's 85 benchmarks: AWFY, then ruby-bench at 09b76c8b0f.
CORPUS = AE::AWFY + %w[
  30k_ifelse 30k_methods activerecord attr_accessor binarytrees blurhash
  cfunc_itself chunky-png erubi erubi-rails etanni fannkuchredux fib fluentd
  gcbench getivar getivar-module graphql graphql-native gvl_release_acquire
  hexapdf json_parse_float json_parse_string keyword_args knucleotide
  knucleotide-ractor lee liquid-c liquid-compile liquid-il liquid-render
  lobsters loops-times mail matmul nbody nqueens object-new
  object-new-initialize object-new-no-escape optcarrot protoboeuf
  protoboeuf-encode psych-load rack railsbench respond_to rubocop ruby-json
  ruby-lsp ruby-xor rubyboy rubykon send_bmethod send_cfunc_block
  send_rubyfunc_block send_rubyfunc_inline sequel setivar setivar_object
  setivar_young shipit splay str_concat string_malloc_pressure structaref
  structaset sudoku symbol-name-ractor throw tinygql
]
assert(CORPUS.size == 85, "corpus size")
quick = AE.selected(CORPUS, "quick")
# Substring filters: the AWFY json/nbody filters pull in four ruby-bench.
assert(quick.size == 39, "quick subset: 14 AWFY + 25 ruby-bench")
assert((quick - AE::FILTERS["quick"]).sort ==
         %w[json_parse_float json_parse_string ruby-json],
       "only the documented extra benchmarks")
assert(AE.selected(CORPUS, "smoke").size == 5, "smoke subset")
assert((AE::HEADLINE + AE::DELEGATION - quick).empty?,
       "claim-carrying benchmarks are in the quick subset")
assert(AE.selected(CORPUS, "full") == CORPUS, "full keeps everything")
assert(AE.flags(%w[a b]) == "--filter a --filter b", "filter flags")

assert(AE.verdict(:zero, 0, nil, nil) == "PASS", "zero")
assert(AE.verdict(:zero, 2, 0, nil) == "WARN", "nonzero")
assert(AE.verdict(:overlap, [1, 0.9, 1.1], [1.2, 1.05, 1.3], nil) == "PASS",
       "overlapping CIs")
assert(AE.verdict(:overlap, [1, 0.9, 1.0], [1.2, 1.05, 1.3], nil) == "WARN",
       "disjoint CIs")
assert(AE.verdict(:below, [0.9, 0.8, 1.01], [0.9, 0.8, 1.0], nil) == "WARN",
       "a CI reaching 1 is not below 1")
assert(AE.verdict(:abs, [0.95, 0.9, 1.0], [1.0, 0.9, 1.1], 0.1) == "PASS",
       "abs compares point estimates")
assert(AE.verdict(:rel, 1.3, 1.0, 0.25) == "WARN", "relative tolerance")
assert(AE.verdict(:positive, [0.2, -0.1, 0.4], nil, nil) == "WARN",
       "a CI reaching 0 is not positive")
assert(AE.verdict(:overlap, nil, [1, 1, 1], nil) == "SKIP", "not run")
assert(AE.verdict(:overlap, [1, 1, 1], nil, nil) == "INFO", "no reference")

Dir.mktmpdir("rpyyarv-ae-test") do |dir|
  perf = File.join(dir, "20260101T000000Z-performance-1")
  stress = File.join(dir, "20260101T000000Z-stress-1")
  camp = File.join(dir, "ae-smoke")
  [perf, stress, camp].each { |d| FileUtils.mkdir_p(d) }
  File.write(File.join(perf, "manifest.json"), '{"kind":"performance"}')
  File.write(File.join(stress, "manifest.json"), '{"kind":"stress"}')
  times = { "cruby" => 10.0, "cruby+yjit" => 4.0, "cruby+zjit" => 5.0,
            "rpyyarv" => 20.0, "rpyyarv-jit" => 2.0 }
  raw = {}
  %w[awfy/richards ruby-bench/keyword_args ruby-bench/lee].each do |b|
    times.each do |e, t|
      raw["#{b}/#{e}"] = { "median" => t, "per_proc" => [t],
                           "raw_iterations" => [[t] * 6], "warmed_at" => [1] }
    end
  end
  File.write(File.join(perf, "raw.json"), JSON.generate(raw))
  File.write(File.join(stress, "stress.csv"), <<~CSV)
    stress,suite,benchmark,engine,outcome,signature,seconds
    c-timer-compact,ruby-bench,shipit,rpyyarv-jit,fail,x,1
    b-dispatch-compact,ruby-bench,lee,rpyyarv,fail,x,1
    b-dispatch-compact,ruby-bench,lee,rpyyarv-jit,timeout,,120
    a-autocompact,ruby-bench,lee,cruby,fail,x,1
  CSV
  File.write(File.join(camp, "campaign.log"),
             "T START a: x\nT END a rc=0 crash_reports=0\n" \
             "T END b rc=2 crash_reports=0\n")
  File.write(File.join(camp, "step-ae-performance.log"),
             "noise\nartifacts: #{perf}\n")
  File.write(File.join(camp, "step-ae-stress.log"), "artifacts: #{stress}\n")
  File.write(File.join(camp, "step-ae-gccheck.log"),
             "gccheck: 13 ok, 1 skipped, 0 failed (RUBY_GC_MALLOC_LIMIT=1)\n")
  runs = AE.collect([camp])
  assert(runs["performance"] == [perf] && runs["stress"] == [stress],
         "campaign dirs expand to their results dirs")
  m = AE.measure(runs, "full")
  assert(m["steps_rc"] == 1, "non-zero step")
  assert(m["gccheck_failed"].zero?, "gccheck summary line")
  assert((m["jit_over_cruby"][0] - 0.2).abs < 1e-9, "jit/cruby geomean")
  assert((m["interp_over_cruby"][0] - 2.0).abs < 1e-9, "interp/cruby")
  assert(m["corpus_failed"].zero?, "no failed benchmark")
  assert(m["headline_ratios"] == { "keyword_args" => 0.5 },
         "headline ratios of the measured benchmarks only")
  assert(m["stress_unexpected"] == 1 && m["stress_timeouts"] == 1,
         "the known crash and CRuby are not charged; lee is")
  m = AE.measure(runs, "smoke")
  assert(m["headline_ratios"].keys == ["keyword_args"] &&
         (m["faster_than_yjit"] - 1.0).abs < 1e-9,
         "smoke drops lee and keeps richards and keyword_args")
end

sig = Stress.signature({ "err_head" => "rpyyarv: no threads (ThreadError)\n",
                         "err_tail" => "", "termsig" => 11 })
assert(sig == "killed by SIGSEGV", "a fatal signal outranks an Error line")
sig = Stress.signature({ "err_head" => "x (ThreadError)\n",
                         "err_tail" => "[BUG] Segmentation fault at 0x1\n" })
assert(sig.start_with?("[BUG]"), "a [BUG] line outranks an Error line")

puts "evaluation tests: ok"
