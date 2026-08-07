#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Run benchmark/*.rb on every available engine and compare best-of-N wall times.
#
# Every benchmark prints a checksum, so a run is only reported when all engines
# agree on stdout; disagreement is flagged as MISMATCH and exits nonzero.

require "open3"

HERE = File.dirname(File.expand_path(__FILE__))
ROOT = File.dirname(HERE)
TOP = File.dirname(ROOT)
BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))

# Shared-library lookup for the CRuby build tree the engines link against.
LIBVAR = RUBY_PLATFORM.include?("darwin") ? "DYLD_LIBRARY_PATH" : "LD_LIBRARY_PATH"

ENGINES = [
  ["cruby",       [File.join(BUILD, "ruby"), "--disable-gems"]],
  ["cruby+yjit",  [File.join(BUILD, "ruby"), "--yjit", "--disable-gems"]],
  ["cruby+zjit",  [File.join(BUILD, "ruby"), "--zjit", "--disable-gems"]],
  ["rpyyarv",     [File.join(ROOT, "rpyyarv")]],
  ["rpyyarv-jit", [File.join(ROOT, "rpyyarv-jit")]]
].freeze

CRUBY_ENGINES = ["cruby", "cruby+yjit", "cruby+zjit"].freeze

def env_for_run
  { LIBVAR => BUILD + File::PATH_SEPARATOR + (ENV[LIBVAR] || "") }
end

def run_once(argv, script, env)
  start = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  out, err, status = Open3.capture3(env, *argv, script)
  elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - start
  unless status.success?
    # The boot path always warns about unloaded default gems; drop that noise.
    msg = err.lines.map(&:chomp).reject { |l| l.include?("not loaded") }.join("\n").strip
    return [nil, elapsed, format("exit %d: %s", status.exitstatus.to_i, msg[-300..] || msg)]
  end
  [out.strip, elapsed, nil]
end

# A JIT flag the build lacks makes ruby exit nonzero before running anything.
def flags_supported?(argv, env)
  system(env, *argv, "-e", "", out: File::NULL, err: File::NULL)
end

def fmt(value)
  value ? format("%.3f", value) : "-"
end

def main(argv)
  reps = 3
  filter = ""
  until argv.empty?
    arg = argv.shift
    case arg
    when /\A--reps=(.*)\z/ then reps = Regexp.last_match(1).to_i
    when "--reps" then reps = argv.shift.to_i
    when /\A--filter=(.*)\z/ then filter = Regexp.last_match(1)
    when "--filter" then filter = argv.shift.to_s
    when "-h", "--help"
      puts "usage: microbench.rb [--reps N] [--filter SUBSTRING]"
      return 0
    else
      warn "unrecognized argument: #{arg}"
      return 2
    end
  end

  bench_dir = File.join(ROOT, "benchmark")
  scripts = Dir.children(bench_dir).select { |f| f.end_with?(".rb") }.sort
  scripts = scripts.select { |f| f.include?(filter) }
  if scripts.empty?
    warn "no benchmarks matched"
    return 1
  end

  env = env_for_run
  engines = []
  ENGINES.each do |name, eargv|
    if !File.executable?(eargv[0])
      puts format("note: skipping %s (%s not found)", name, eargv[0])
    elsif !flags_supported?(eargv, env)
      puts format("note: skipping %s (flags unsupported by this build)", name)
    else
      engines << [name, eargv]
    end
  end
  if engines.empty?
    warn "no engines available"
    return 1
  end

  rows = []
  failed = false

  scripts.each do |script|
    path = File.join(bench_dir, script)
    name = script[0..-4]
    times = {}
    outputs = {}
    notes = []
    engines.each do |ename, eargv|
      best = nil
      reps.times do
        out, elapsed, err = run_once(eargv, path, env)
        unless err.nil?
          notes << format("%s CRASH (%s)", ename, err)
          best = nil
          break
        end
        outputs[ename] = out unless outputs.key?(ename)
        notes << format("%s UNSTABLE OUTPUT across reps", ename) if outputs[ename] != out
        best = best.nil? ? elapsed : [best, elapsed].min
      end
      times[ename] = best
      failed = true if best.nil?
    end

    distinct = outputs.values.uniq
    if distinct.size > 1
      failed = true
      notes << "MISMATCH: " + outputs.sort.map { |e, o| format("%s=%s", e, o.inspect) }.join("; ")
    end
    checksum = distinct.size == 1 ? distinct.sort[0] : "?"
    rows << [name, checksum, times, notes]
    puts format("ran %-14s checksum=%s%s", name, checksum,
                notes.empty? ? "" : "  [" + notes.join(" | ") + "]")
  end

  puts
  headers = ["benchmark"] + engines.map { |e, _| e } + ["speedup"]
  table = []
  rows.each do |name, _checksum, times, _notes|
    cells = [name] + engines.map { |e, _| fmt(times[e]) }
    # Speedup vs the fastest CRuby variant: >1 means rpyyarv-jit is faster.
    best_c = CRUBY_ENGINES.map { |e| times[e] }.compact.min
    j = times["rpyyarv-jit"]
    cells << (best_c && j && j > 0 ? format("%.2fx", best_c / j) : "-")
    table << cells
  end

  widths = (0...headers.size).map { |i| ([headers] + table).map { |r| r[i].length }.max }
  line = lambda do |r|
    r.each_with_index.map { |c, i| i.zero? ? c.ljust(widths[i]) : c.rjust(widths[i]) }.join("  ")
  end
  puts line.call(headers)
  puts widths.map { |w| "-" * w }.join("  ")
  table.each { |r| puts line.call(r) }
  puts format("\nbest of %d reps, seconds; speedup = fastest CRuby / rpyyarv-jit", reps)

  if failed
    warn "\nFAILED: see notes above"
    return 1
  end
  0
end

exit(main(ARGV)) if __FILE__ == $PROGRAM_NAME
