#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Steady-state AWFY runner: time each inner_benchmark_loop call in a warm
# process and report the median of the measured iterations, not the first run.
#
# AWFY's own harness.rb is unusable here: run.rb uses getspecial, so rpyyarv
# punts the whole file to CRuby and the benchmark silently runs under CRuby.
# This generates a drv_*.rb-style driver instead.

require "open3"
require "tmpdir"

HERE = File.dirname(File.expand_path(__FILE__))
ROOT = File.dirname(HERE)
TOP = File.dirname(ROOT)
BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
AWFY = File.join(ROOT, "awfy", "benchmarks", "Ruby")

LIBVAR = RUBY_PLATFORM.include?("darwin") ? "DYLD_LIBRARY_PATH" : "LD_LIBRARY_PATH"

ENGINES = [
  ["cruby",       [File.join(BUILD, "ruby"), "--disable-gems"]],
  ["cruby+yjit",  [File.join(BUILD, "ruby"), "--disable-gems", "--yjit"]],
  ["cruby+zjit",  [File.join(BUILD, "ruby"), "--disable-gems", "--zjit"]],
  ["rpyyarv",     [File.join(ROOT, "rpyyarv")]],
  ["rpyyarv-jit", [File.join(ROOT, "rpyyarv-jit")]]
].freeze

# name => [class, inner, warmup, measured]; inner targets ~80 ms per iteration
# under CRuby. cd, havlak, mandelbrot and nbody only verify at fixed inner
# values, so those take the nearest allowed one and fewer iterations instead.
BENCHMARKS = {
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

# Only the children get these: DYLD_LIBRARY_PATH pointing at the build tree
# breaks whatever ruby runs this harness.
def env_for_run
  env = { LIBVAR => BUILD + File::PATH_SEPARATOR + (ENV[LIBVAR] || "") }
  env["RUBYLIB"] = ENV["AWFY_RUBYLIB"] if ENV["AWFY_RUBYLIB"]
  env
end

def driver_source(name, klass, inner, warm, meas)
  <<~RUBY
    require_relative '#{name}'
    b = #{klass}.new
    ok = true
    #{warm + meas}.times do |i|
      t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      r = b.inner_benchmark_loop(#{inner})
      t1 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      ok = false unless r == true
      puts "ITER " + i.to_s + " " + ((t1 - t0) * 1000.0).to_s + " " + r.to_s
    end
    puts "DONE " + ok.to_s
  RUBY
end

# The driver has to sit next to the benchmark so require_relative resolves.
def with_driver(name, src)
  path = File.join(AWFY, "awfy_tmp_drv_#{name}_#{Process.pid}.rb")
  File.write(path, src)
  yield path
ensure
  File.unlink(path) if path && File.exist?(path)
end

def run_series(argv, script, env)
  out, err, status = Open3.capture3(env, *argv, script)
  unless status.success?
    msg = err.lines.map(&:chomp).reject { |l| l.include?("not loaded") }.join("\n").strip
    return [nil, format("exit %d: %s", status.exitstatus.to_i, msg[-300..] || msg)]
  end
  times = []
  verdicts = []
  done = nil
  out.each_line do |l|
    case l
    when /\AITER \d+ (\S+) (\S+)/ then times << Regexp.last_match(1).to_f
                                       verdicts << Regexp.last_match(2)
    when /\ADONE (\S+)/ then done = Regexp.last_match(1)
    end
  end
  return [nil, "driver produced no DONE line"] if done.nil?
  return [nil, "inner_benchmark_loop returned a non-true verdict"] if done != "true"
  bad = verdicts.reject { |v| v == "true" }
  return [nil, "bad verdicts: #{bad.uniq.inspect}"] unless bad.empty?
  [times, nil]
end

def median(a)
  return nil if a.empty?
  s = a.sort
  n = s.size
  n.odd? ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2.0
end

def fmt(v)
  v ? format("%.2f", v) : "-"
end

def main(argv)
  procs = 3
  filters = []
  raw_path = nil
  until argv.empty?
    arg = argv.shift
    case arg
    when /\A--procs=(.*)\z/ then procs = Regexp.last_match(1).to_i
    when "--procs" then procs = argv.shift.to_i
    when /\A--filter=(.*)\z/ then filters << Regexp.last_match(1)
    when "--filter" then filters << argv.shift.to_s
    when /\A--raw=(.*)\z/ then raw_path = Regexp.last_match(1)
    when "-h", "--help"
      puts "usage: awfy.rb [--procs N] [--filter SUBSTRING]... [--raw FILE]"
      return 0
    else
      warn "unrecognized argument: #{arg}"
      return 2
    end
  end

  env = env_for_run
  engines = ENGINES.select do |name, eargv|
    if !File.executable?(eargv[0])
      puts format("note: skipping %s (%s not found)", name, eargv[0])
      false
    elsif !system(env, *eargv, "-e", "", out: File::NULL, err: File::NULL)
      puts format("note: skipping %s (flags unsupported by this build)", name)
      false
    else
      true
    end
  end
  return 1 if engines.empty?

  # Repeated --filter is a union, not a last-one-wins overwrite.
  names = BENCHMARKS.keys.select { |n| filters.empty? || filters.any? { |f| n.include?(f) } }
  rows = []
  raw = {}

  names.each do |name|
    klass, inner, warm, meas = BENCHMARKS[name]
    src = driver_source(name, klass, inner, warm, meas)
    result = {}
    with_driver(name, src) do |path|
      engines.each do |ename, eargv|
        pooled = []
        firsts = []
        error = nil
        procs.times do
          times, err = run_series(eargv, path, env)
          if err
            error = err
            break
          end
          firsts << times.first
          pooled.concat(times[warm..] || [])
        end
        raw["#{name}/#{ename}"] = { "first" => firsts, "measured" => pooled, "error" => error }
        result[ename] = error ? { err: error } : {
          median: median(pooled), min: pooled.min, first: median(firsts), n: pooled.size
        }
        puts format("  %-12s %-12s %s", name, ename,
                    error ? "INVALID: #{error}" : format("median %.2f ms  min %.2f  first %.2f  (n=%d)",
                                                         result[ename][:median], result[ename][:min],
                                                         result[ename][:first], result[ename][:n]))
      end
    end
    rows << [name, inner, warm, meas, result]
  end

  puts
  headers = ["benchmark", "inner"] + engines.map { |e, _| e } + ["jit/cruby", "jit/yjit"]
  table = rows.map do |name, inner, _w, _m, result|
    cells = [name, inner.to_s] + engines.map { |e, _| result[e][:err] ? "INVALID" : fmt(result[e][:median]) }
    j = result["rpyyarv-jit"] && result["rpyyarv-jit"][:median]
    c = result["cruby"] && result["cruby"][:median]
    y = result["cruby+yjit"] && result["cruby+yjit"][:median]
    cells << (j && c ? format("%.2fx", j / c) : "-")
    cells << (j && y ? format("%.2fx", j / y) : "-")
    cells
  end
  widths = (0...headers.size).map { |i| ([headers] + table).map { |r| r[i].to_s.length }.max }
  line = ->(r) { r.each_with_index.map { |c, i| i.zero? ? c.to_s.ljust(widths[i]) : c.to_s.rjust(widths[i]) }.join("  ") }
  puts line.call(headers)
  puts widths.map { |w| "-" * w }.join("  ")
  table.each { |r| puts line.call(r) }
  puts format("\nsteady-state median ms per inner_benchmark_loop(inner), pooled over %d processes; ratio <1 means rpyyarv-jit is faster", procs)

  if raw_path
    require "json"
    File.write(raw_path, JSON.pretty_generate(raw))
    puts "raw series: #{raw_path}"
  end
  0
end

exit(main(ARGV)) if __FILE__ == $PROGRAM_NAME
