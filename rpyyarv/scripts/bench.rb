#!/usr/bin/env ruby
# frozen_string_literal: true
#
# One driver for AWFY and ruby-bench; timing and aggregation are shared.
# Suite harnesses use getspecial/retry, so they would silently time CRuby.
# A TIMED RUN MUST NEVER CARRY INSTRUMENTATION ENV (coverage: cd 200->172 ms).

require "open3"
require "json"

HERE = File.dirname(File.expand_path(__FILE__))
ROOT = File.dirname(HERE)
TOP = File.dirname(ROOT)
BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
AWFY_DIR = File.join(ROOT, "awfy", "benchmarks", "Ruby")
SHIM_DIR = File.join(HERE, "ruby-bench")
INVENTORY_PATH = File.join(ROOT, ".bench-inventory.json")

LIBVAR = RUBY_PLATFORM.include?("darwin") ? "DYLD_LIBRARY_PATH" : "LD_LIBRARY_PATH"

BASE_ENGINES = [
  ["cruby",       [File.join(BUILD, "ruby"), "--disable-gems"]],
  ["cruby+yjit",  [File.join(BUILD, "ruby"), "--disable-gems", "--yjit"]],
  ["cruby+zjit",  [File.join(BUILD, "ruby"), "--disable-gems", "--zjit"]],
  ["rpyyarv",     [File.join(ROOT, "rpyyarv")]],
  ["rpyyarv-jit", [File.join(ROOT, "rpyyarv-jit")]]
].freeze

# name => [class, inner, warmup, measured]; inner targets ~80 ms under CRuby.
# cd/havlak/mandelbrot/nbody verify only at fixed inner values, so fewer iters.
AWFY_BENCHMARKS = {
  "bounce"     => ["Bounce",     200,    10, 15],
  "cd"         => ["CD",         100,    10, 15],
  "deltablue"  => ["DeltaBlue",  5000,   10, 15],
  "havlak"     => ["Havlak",     150,    6,  8],
  "json"       => ["Json",       20,     10, 15],
  "list"       => ["List",       200,    10, 15],
  "mandelbrot" => ["Mandelbrot", 500,    6,  8],
  "nbody"      => ["NBody",      250_000, 6, 8],
  "permute"    => ["Permute",    100,    10, 15],
  "queens"     => ["Queens",     150,    10, 15],
  "richards"   => ["Richards",   5,      10, 15],
  "sieve"      => ["Sieve",      200,    10, 15],
  "storage"    => ["Storage",    150,    10, 15],
  "towers"     => ["Towers",     75,     10, 15]
}.freeze

BIMODAL_RATIO = 1.15
DRV_PREFIX = "bench_tmp_drv_"

# --- shared machinery -------------------------------------------------------

# Children only: pointing DYLD_LIBRARY_PATH at build breaks this harness's ruby.
def base_env
  { LIBVAR => BUILD + File::PATH_SEPARATOR + (ENV[LIBVAR] || "") }
end

def uninstalled_rubylib
  arch = Dir[File.join(BUILD, ".ext", "*", "zlib.{bundle,so}")].first
  [File.join(TOP, "lib"), File.join(BUILD, ".ext", "common"), BUILD,
   arch && File.dirname(arch), ENV["RUBYLIB"]].compact.join(File::PATH_SEPARATOR)
end

# Only the probe gets this; see the header note on cd 172 vs 200 ms.
COVERAGE_ENV = { "RPYYARV_COVERAGE" => "1" }.freeze

# The gem set bench-setup filled, so Bundler.setup finds the pinned versions.
BENCH_GEMS = ENV.fetch("BENCH_GEMS", File.join(ROOT, ".bench-gems"))

def bench_gems_env
  return {} unless File.directory?(BENCH_GEMS)
  { "GEM_HOME" => BENCH_GEMS, "GEM_PATH" => BENCH_GEMS,
    "BUNDLE_PATH" => BENCH_GEMS,
    "BUNDLE_APP_CONFIG" => File.join(BENCH_GEMS, ".bundle") }
end

def rubylib
  ENV["AWFY_RUBYLIB"].to_s
end

def median(a)
  return nil if a.nil? || a.empty?
  s = a.sort
  n = s.size
  n.odd? ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2.0
end

def geomean(a)
  return nil if a.empty?
  Math.exp(a.sum { |v| Math.log(v) } / a.size)
end

def fmt(v)
  v ? format("%.2f", v) : "-"
end

# perl's alarm is what the rest of this repo uses to bound a child run.
def timeout_argv(secs, argv)
  ["perl", "-e", "alarm shift; exec @ARGV", secs.to_s] + argv
end

# Returns [times, err, info]; a delegated run is an error, never a number.
def run_once(argv, script, env, timeout)
  out, err, status = Open3.capture3(env, *timeout_argv(timeout, argv + [script]))
  # Benchmarks emit binary data; scrub before any regex touches it.
  out = out.scrub
  err = err.scrub
  text = out + err
  info = coverage_of(text)
  # Per-file delegation stays a number; only a wholesale CRuby run misleads.
  if text.include?("running under CRuby instead")
    return [nil, "DELEGATED", info.merge("delegated" => first_delegation(text))]
  end
  unless status.success?
    return [nil, status.exitstatus == 142 ? "TIMEOUT" : "FAIL",
            info.merge("why" => why(err, status),
                       "err_tail" => err[-1500..-1] || err)]
  end
  times = []
  done = nil
  out.each_line do |l|
    case l
    when /\AITER \d+ (\S+) (\S+)/
      return [nil, "FAIL", info.merge("why" => "bad verdict #{Regexp.last_match(2)}")] if Regexp.last_match(2) != "true"
      times << Regexp.last_match(1).to_f
    when /\AWARMED (\d+)/ then info["warmed"] = Regexp.last_match(1).to_i
    when /\ADONE (\S+)/ then done = Regexp.last_match(1)
    end
  end
  if done != "true"
    return [nil, "FAIL", info.merge("why" => "no DONE line",
                                    "err_tail" => err[-1500..-1] || err)]
  end
  [times, nil, info]
end

def coverage_of(text)
  info = {}
  info["iseqs"] = Regexp.last_match(1) if text =~ /iseqs: (\d+\/\d+)/
  if text =~ /files: rpyyarv (\d+), delegated to cruby (\d+)/
    info["files_native"] = Regexp.last_match(1).to_i
    info["files_delegated"] = Regexp.last_match(2).to_i
  end
  info
end

def first_delegation(text)
  return Regexp.last_match(1).strip.sub(/\A.*?\.rb: /, "") if text =~ /delegated to cruby: (.*)/
  "delegated"
end

# Benign noise a run prints anyway: the reaper-thread refusal, debug counts.
WHY_NOISE = /another thread is not supported|terminated with exception|invalidation #/

def why(err, status)
  msg = err.lines.map(&:chomp)
           .reject { |l| l.include?("not loaded") || l =~ WHY_NOISE }
           .grep(/rror|xception|undefined|rpyyarv|undler|ould not find/).first
  return "exit #{status.exitstatus}" unless msg
  msg.gsub(%r{\S*/bench_tmp_drv_\S+\.rb:?}, "").strip[0, 100]
end

# Engines are interleaved process by process, not suite after suite.
def time_engine(argv, script, env, warm, procs, timeout)
  pooled = []
  per_proc = []
  procs.times do
    times, err, info = run_once(argv, script, env, timeout)
    if err
      return { status: err, why: info["why"], err_tail: info["err_tail"] }
    end
    # The harness says where warmup ended when WARMUP_TIME stretched it.
    w = info["warmed"] || warm
    pooled.concat(times[w..] || [])
    per_proc << median(times[w..] || times)
  end
  spread = per_proc.compact.empty? ? nil : per_proc.compact.max / per_proc.compact.min
  { median: median(pooled), min: pooled.min, n: pooled.size,
    per_proc: per_proc, spread: spread }
end

def render_table(headers, table)
  widths = (0...headers.size).map { |i| ([headers] + table).map { |r| r[i].to_s.length }.max }
  line = ->(r) { r.each_with_index.map { |c, i| i.zero? ? c.to_s.ljust(widths[i]) : c.to_s.rjust(widths[i]) }.join("  ") }
  puts line.call(headers)
  puts widths.map { |w| "-" * w }.join("  ")
  table.each { |r| puts line.call(r) }
end

# --- suites -----------------------------------------------------------------

# AWFY: a generated driver next to the benchmark so require_relative resolves.
class AwfySuite
  attr_reader :name

  def initialize(_opts)
    @name = "awfy"
  end

  def available? = File.directory?(AWFY_DIR)

  def missing_message = "AWFY checkout not found at #{AWFY_DIR}"

  def benchmarks = AWFY_BENCHMARKS.keys

  def label(bench) = AWFY_BENCHMARKS[bench][1].to_s

  def timeout = 600

  # A probe runs one iteration at the real inner count: enough to load the file.
  def with_script(bench, probe: false)
    klass, inner, warm, meas = AWFY_BENCHMARKS[bench]
    src = <<~RUBY
      require_relative '#{bench}'
      b = #{klass}.new
      ok = true
      #{probe ? 1 : warm + meas}.times do |i|
        t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        r = b.inner_benchmark_loop(#{inner})
        t1 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        ok = false unless r == true
        puts "ITER " + i.to_s + " " + ((t1 - t0) * 1000.0).to_s + " " + r.to_s
      end
      puts "DONE " + ok.to_s
    RUBY
    path = File.join(AWFY_DIR, "awfy_tmp_drv_#{bench}_#{Process.pid}.rb")
    File.write(path, src)
    env = base_env
    lib = rubylib
    env["RUBYLIB"] = lib unless lib.empty?
    yield path, env, warm
  ensure
    File.unlink(path) if path && File.exist?(path)
  end
end

# ruby-bench: the benchmark file itself, run against the shim harness.
class RubyBenchSuite
  attr_reader :name, :dir

  def initialize(opts)
    @name = "ruby-bench"
    @warm = opts[:warmup] || 5
    @meas = opts[:iters] || 5
    @gem_require = opts[:gem_require]
    # An explicit --ruby-bench is used as given, never replaced by a fallback.
    candidates = opts[:dir] ? [opts[:dir]] : [ENV["RUBY_BENCH"], File.join(ROOT, "ruby-bench"),
                                              File.join(ROOT, "yjit-bench")].compact
    @dir = candidates.find { |d| File.directory?(File.join(d, "benchmarks")) }
  end

  def available? = !@dir.nil?

  def missing_message
    "ruby-bench checkout not found; pass --ruby-bench DIR, set $RUBY_BENCH, or:\n" \
      "  git clone --depth=1 https://github.com/ruby/ruby-bench #{File.join(ROOT, 'ruby-bench')}"
  end

  def benchmarks = paths.keys.sort

  def label(_bench) = "-"

  def timeout = 600

  def paths
    @paths ||= begin
      h = {}
      # A driver left behind by a killed run must not look like a benchmark.
      Dir[File.join(@dir, "benchmarks", "**", "#{DRV_PREFIX}*.rb")].each { |f| File.unlink(f) }
      Dir[File.join(@dir, "benchmarks", "*.rb")].each { |f| h[File.basename(f, ".rb")] = f }
      Dir[File.join(@dir, "benchmarks", "*", "benchmark.rb")].each { |f| h[File.basename(File.dirname(f))] = f }
      h
    end
  end

  def gems?(bench) = File.exist?(File.join(File.dirname(paths[bench]), "Gemfile"))

  # Probed once and cached: a gem tree RPyYARV cannot load must not crash it.
  def native_requires?(bench)
    return @gem_require unless @gem_require.nil?
    @native ||= {}
    return @native[bench] if @native.key?(bench)
    @native[bench] = probe_native_requires(bench)
  end

  def probe_native_requires(bench)
    ok = false
    with_script(bench, probe: true, force_native: true) do |script, env, _w|
      _t, err, = run_once([File.join(ROOT, "rpyyarv")], script, env, 120)
      ok = err.nil?
    end
    puts format("  %-24s gems: %s", bench, ok ? "rpyyarv" : "cruby")
    ok
  end

  # The shim is inlined and harness/loader dropped: loader.rb uses retry.
  # The driver sits in the benchmark's dir so __dir__ and requires resolve.
  def with_script(bench, probe: false, force_native: false)
    warm = probe ? 0 : @warm
    meas = probe ? 1 : @meas
    # Before the driver is written: the probe's ensure would delete it.
    no_require = gems?(bench) && !force_native && !native_requires?(bench)
    src = File.read(paths[bench]).gsub(/^\s*require_relative\s+['"][.\/]*harness\/loader['"].*$/, "")
    path = File.join(File.dirname(paths[bench]), "#{DRV_PREFIX}#{bench}_#{Process.pid}.rb")
    File.write(path, File.read(File.join(SHIM_DIR, "harness.rb")) + "\n" + src)
    env = base_env.merge("WARMUP_ITRS" => warm.to_s,
                         # Wall-clock warmup floor: a tracing JIT needs it.
                         "WARMUP_TIME" => probe ? "0" : "5",
                         "MIN_BENCH_ITRS" => meas.to_s,
                         # Long enough that ~300 ms stalls land in every window.
                         "MIN_BENCH_TIME" => probe ? "0" : "5",
                         "RUBYLIB" => uninstalled_rubylib).merge(bench_gems_env)
    # RPyYARV must not re-load RubyGems' tree: it redefines Gem and crashes.
    env["RPYYARV_NO_REQUIRE"] = "1" if no_require
    yield path, env, warm
  ensure
    File.unlink(path) if path && File.exist?(path)
  end
end

# --- coverage ---------------------------------------------------------------

# A probe, never a timed run: RPYYARV_COVERAGE=1 changes JIT selection.
def foreign_report(suite, names, top)
  names.each do |bench|
    suite.with_script(bench, probe: true) do |script, env, _warm|
      out, err, = Open3.capture3(env.merge(COVERAGE_ENV),
                                 *timeout_argv(suite.timeout, [File.join(ROOT, "rpyyarv"), script]))
      text = (out + err).scrub
      sends = text[/sends: rpyyarv (\d+), cruby (\d+)/, 0] || "sends: -"
      puts format("%-24s %s", bench, sends)
      text.scan(/^\[rpyyarv\]   cruby (?:send|site): (.*)$/).flatten.first(top).each do |l|
        puts format("  %-22s %s", "", l)
      end
      # Why files delegate, folded to the root cause so gems aggregate.
      reasons = Hash.new(0)
      text.scan(/^\[rpyyarv\]   delegated to cruby: (.*)$/).flatten.each do |l|
        reasons[l[/'\w+' is not implemented/] || l.sub(/\A\S+ /, "")] += 1
      end
      reasons.sort_by { |_, n| -n }.first(top).each do |r, n|
        puts format("  %-22s %4d file(s): %s", "", n, r)
      end
    end
  end
end

# --- inventory --------------------------------------------------------------

def load_inventory
  File.exist?(INVENTORY_PATH) ? JSON.parse(File.read(INVENTORY_PATH)) : {}
rescue JSON::ParserError
  {}
end

# Classify: NATIVE / DELEGATED / CRASH / TIMEOUT / NEEDS-GEMS.
# A Gemfile alone is not a verdict; it only explains a failure.
def probe(suite, bench)
  suite.with_script(bench, probe: true) do |script, env, _warm|
    _times, err, info = run_once([File.join(ROOT, "rpyyarv")], script, env.merge(COVERAGE_ENV), 90)
    failure = info["why"].to_s
    status = case err
             when nil then "NATIVE"
             when "DELEGATED" then "DELEGATED"
             when "TIMEOUT" then "TIMEOUT"
             else suite.gems?(bench) &&
                  failure.match?(/Bundler|Could not find|cannot load such file/) ? "NEEDS-GEMS" : "CRASH"
             end
    why = info["delegated"] || info["why"]
    why = "#{why}; bundle install in #{File.dirname(suite.paths[bench])}" if status == "NEEDS-GEMS"
    return { "status" => status, "why" => why, "iseqs" => info["iseqs"] }
  end
end

def inventory_for(suite, names, refresh)
  cache = load_inventory
  names.each do |bench|
    next if cache[bench] && !refresh
    cache[bench] = probe(suite, bench)
    puts format("  %-24s %-10s %s", bench, cache[bench]["status"], cache[bench]["why"] || "")
    File.write(INVENTORY_PATH, JSON.pretty_generate(cache))
  end
  File.write(INVENTORY_PATH, JSON.pretty_generate(cache))
  cache
end

# --- run --------------------------------------------------------------------

def resolve_engines(extra, env)
  list = BASE_ENGINES.map { |n, a| [n, a] } + extra
  list.select do |name, argv|
    if !File.executable?(argv[0])
      puts format("note: skipping %s (%s not found)", name, argv[0])
      false
    elsif !system(env, *argv, "-e", "", out: File::NULL, err: File::NULL)
      puts format("note: skipping %s (flags unsupported by this build)", name)
      false
    else
      true
    end
  end
end

def run_suite(suite, names, engines, procs, raw)
  rows = []
  names.each do |bench|
    result = {}
    skip = suite.respond_to?(:skip_reason) ? suite.skip_reason(bench) : nil
    if skip
      puts format("  %-16s SKIP: %s", bench, skip)
      rows << [bench, suite.label(bench), {}, skip]
      next
    end
    # Verdict and coverage come from the probe; the timed series runs clean.
    probes = {}
    suite.with_script(bench, probe: true) do |script, env, _warm|
      engines.each do |ename, eargv|
        _t, err, info = run_once(eargv, script, env.merge(COVERAGE_ENV), suite.timeout)
        probes[ename] = [err, info]
      end
    end
    suite.with_script(bench) do |script, env, warm|
      engines.each do |ename, eargv|
        perr, pinfo = probes[ename]
        r = perr ? { status: perr, info: pinfo } : time_engine(eargv, script, env, warm, procs, suite.timeout)
        r[:info] = pinfo
        result[ename] = r
        raw["#{suite.name}/#{bench}/#{ename}"] = r
        puts format("  %-16s %-12s %s", bench, ename,
                    r[:status] || format("median %.2f ms  min %.2f  spread %.2fx  (n=%d)",
                                         r[:median], r[:min], r[:spread] || 1.0, r[:n]))
      end
    end
    rows << [bench, suite.label(bench), result, nil]
  end
  rows
end

def ratio_columns(engines)
  extra = engines.map(&:first) - BASE_ENGINES.map(&:first)
  [["jit/cruby", "rpyyarv-jit", "cruby"], ["jit/yjit", "rpyyarv-jit", "cruby+yjit"]] +
    extra.map { |e| ["#{e}/jit", e, "rpyyarv-jit"] }
end

def cell(result, ename)
  r = result[ename]
  return "-" unless r
  r[:status] || fmt(r[:median])
end

def value(result, ename)
  r = result[ename]
  r && r[:status].nil? ? r[:median] : nil
end

def report(suite_name, rows, engines, procs)
  ratios = ratio_columns(engines)
  headers = ["benchmark", "size"] + engines.map(&:first) + ratios.map(&:first) + ["spread", "note"]
  table = rows.map do |bench, lbl, result, skip|
    if skip
      next [bench, lbl] + engines.map { "SKIP" } + ratios.map { "-" } + ["-", skip[0, 40]]
    end
    cells = [bench, lbl] + engines.map { |e, _| cell(result, e) }
    ratios.each do |_h, num, den|
      n = value(result, num)
      d = value(result, den)
      cells << (n && d ? format("%.2fx", n / d) : "-")
    end
    primary = result["rpyyarv-jit"] || result[engines.first.first]
    spread = primary && primary[:spread]
    cells << (spread ? format("%.2fx", spread) : "-")
    note = []
    note << "BIMODAL?" if spread && spread > BIMODAL_RATIO
    note << "iseqs #{primary[:info]['iseqs']}" if primary && primary[:info] && primary[:info]["iseqs"]
    if primary && primary[:info] && primary[:info]["files_delegated"].to_i > 0
      note << "#{primary[:info]['files_delegated']} file(s) delegated"
    end
    cells << note.join(" ")
    cells
  end
  puts
  puts "== #{suite_name} =="
  render_table(headers, table)
  puts format("steady-state median ms, pooled over %d process(es); ratio <1 means the numerator is faster; " \
              "spread = max/min of the per-process medians, >%.2fx is flagged BIMODAL?", procs, BIMODAL_RATIO)
end

def summarize(all_rows, engines)
  ratios = ratio_columns(engines)
  puts
  puts "== combined summary =="
  headers = ["suite", "n native", "n delegated", "n excluded"] + ratios.map { |h, _, _| "geomean #{h}" }
  table = []
  totals = Hash.new { |h, k| h[k] = [] }
  all_rows.each do |suite_name, rows|
    # From rpyyarv-jit's verdict: a cruby number says nothing about rpyyarv.
    primary = engines.map(&:first).include?("rpyyarv-jit") ? "rpyyarv-jit" : engines.first.first
    verdicts = rows.map { |_b, _l, r, s| s ? "SKIP" : (r[primary] && r[primary][:status]) }
    native = verdicts.count(&:nil?)
    delegated = verdicts.count("DELEGATED")
    excluded = verdicts.size - native - delegated
    cells = [suite_name, native.to_s, delegated.to_s, excluded.to_s]
    ratios.each do |h, num, den|
      vals = rows.filter_map do |_b, _l, r, s|
        next if s
        n = value(r, num)
        d = value(r, den)
        n && d ? n / d : nil
      end
      totals[h].concat(vals)
      g = geomean(vals)
      cells << (g ? format("%.2fx (n=%d)", g, vals.size) : "-")
    end
    table << cells
  end
  overall = ["all", "-", "-", "-"] + ratios.map do |h, _n, _d|
    g = geomean(totals[h])
    g ? format("%.2fx (n=%d)", g, totals[h].size) : "-"
  end
  table << overall
  render_table(headers, table)
  puts "geometric mean over benchmarks that produced a number under both engines; DELEGATED/FAIL rows are counted, not dropped"
end

def main(argv)
  procs = 3
  filters = []
  raw_path = nil
  suites = nil
  extra_engines = []
  opts = {}
  inventory_only = false
  foreign_top = nil
  refresh = false
  until argv.empty?
    arg = argv.shift
    case arg
    when /\A--procs=(.*)\z/ then procs = Regexp.last_match(1).to_i
    when "--procs" then procs = argv.shift.to_i
    when /\A--filter=(.*)\z/ then filters << Regexp.last_match(1)
    when "--filter" then filters << argv.shift.to_s
    when /\A--raw=(.*)\z/ then raw_path = Regexp.last_match(1)
    when "--raw" then raw_path = argv.shift
    when /\A--suite=(.*)\z/ then suites = Regexp.last_match(1)
    when "--suite" then suites = argv.shift
    when /\A--ruby-bench=(.*)\z/ then opts[:dir] = Regexp.last_match(1)
    when "--ruby-bench" then opts[:dir] = argv.shift
    when /\A--warmup=(.*)\z/ then opts[:warmup] = Regexp.last_match(1).to_i
    when "--warmup" then opts[:warmup] = argv.shift.to_i
    when /\A--iters=(.*)\z/ then opts[:iters] = Regexp.last_match(1).to_i
    when "--iters" then opts[:iters] = argv.shift.to_i
    when /\A--engine=(.*)\z/, "--engine"
      spec = arg.start_with?("--engine=") ? Regexp.last_match(1) : argv.shift.to_s
      n, path = spec.split("=", 2)
      return 2 unless path
      extra_engines << [n, [File.expand_path(path)]]
    when "--compare" then extra_engines << ["alt", [File.expand_path(argv.shift.to_s)]]
    when /\A--foreign(?:=(\d+))?\z/ then foreign_top = (Regexp.last_match(1) || 12).to_i
    when "--gem-require" then opts[:gem_require] = true
    when "--no-gem-require" then opts[:gem_require] = false
    when "--inventory" then inventory_only = true
    when "--refresh-inventory" then refresh = true
    when "-h", "--help"
      puts <<~USAGE
        usage: bench.rb [--suite awfy|ruby-bench|all] [--procs N] [--filter SUBSTRING]...
                        [--ruby-bench DIR] [--warmup N] [--iters N] [--raw FILE]
                        [--engine NAME=PATH]... [--compare BIN] [--inventory] [--refresh-inventory]
                        [--foreign[=N]] [--gem-require|--no-gem-require]
        By default each Gemfile benchmark is probed once for whether RPyYARV can
        own its gem requires, and timed the way the probe says. --gem-require
        forces it on for every benchmark, --no-gem-require leaves every require
        to CRuby; RubyGems' own tree crashes RPyYARV either way.
        --foreign runs the coverage probe only and ranks what each benchmark still
        sends to CRuby; it prints no timings, since coverage perturbs them.
        --engine/--compare add an engine that is timed interleaved with the others and
        gets its own ratio column against rpyyarv-jit.
      USAGE
      return 0
    else
      warn "unrecognized argument: #{arg}"
      return 2
    end
  end

  wanted = case (suites || "all")
           when "awfy" then ["awfy"]
           when "yjit", "yjit-bench", "ruby-bench" then ["ruby-bench"]
           when "all" then ["awfy", "ruby-bench"]
           else warn "unknown suite: #{suites}"; return 2
           end

  env = base_env
  engines = resolve_engines(extra_engines, env)
  return 1 if engines.empty?

  all_rows = []
  raw = {}
  wanted.each do |sname|
    suite = sname == "awfy" ? AwfySuite.new(opts) : RubyBenchSuite.new(opts)
    unless suite.available?
      warn suite.missing_message
      next
    end
    names = suite.benchmarks.select { |n| filters.empty? || filters.any? { |f| n.include?(f) } }
    if foreign_top
      foreign_report(suite, names, foreign_top)
      next
    end
    if suite.is_a?(RubyBenchSuite)
      inv = inventory_for(suite, names, refresh || inventory_only)
      # Delegated benchmarks are still timed; only unrunnable ones become rows.
      suite.define_singleton_method(:skip_reason) do |bench|
        s = inv[bench] && inv[bench]["status"]
        s && !%w[NATIVE DELEGATED].include?(s) ? "#{s}: #{inv[bench]['why']}" : nil
      end
      next if inventory_only
    end
    rows = run_suite(suite, names, engines, procs, raw)
    report(suite.name, rows, engines, procs)
    all_rows << [suite.name, rows]
  end

  return 0 if inventory_only
  summarize(all_rows, engines) unless all_rows.empty?

  if raw_path
    File.write(raw_path, JSON.pretty_generate(raw))
    puts "raw series: #{raw_path}"
  end
  0
end

exit(main(ARGV)) if __FILE__ == $PROGRAM_NAME
