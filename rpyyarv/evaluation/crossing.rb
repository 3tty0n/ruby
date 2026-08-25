#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Microbenchmark for the cost of one native->CRuby boundary crossing.
# Automates the manual measurement in docs/native-vs-delegated.org
# ("境界 1 回の値段"): time a kernel expr N times, subtract the empty-loop
# cost, and compare rpyyarv-jit's net cost against CRuby's for the same expr.

require "fileutils"
require "json"
require "open3"
require "optparse"
require "tmpdir"

module CrossingBench
  HERE = File.dirname(File.expand_path(__FILE__))
  ROOT = File.expand_path("..", HERE)
  TOP = File.expand_path("..", ROOT)
  BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
  LIBVAR = RUBY_PLATFORM.include?("darwin") ? "DYLD_LIBRARY_PATH" : "LD_LIBRARY_PATH"

  ENGINES = [
    ["cruby",       [File.join(BUILD, "ruby"), "--disable-gems"]],
    ["cruby+yjit",  [File.join(BUILD, "ruby"), "--yjit", "--disable-gems"]],
    ["rpyyarv",     [File.join(ROOT, "rpyyarv")]],
    ["rpyyarv-jit", [File.join(ROOT, "rpyyarv-jit")]]
  ].freeze

  # "empty" is the calibration loop body; its net_ns is always 0 by
  # definition and is what the other kernels' raw_ns get subtracted by.
  KERNELS = {
    "empty" => "x",
    "to_sym" => "s.to_sym",
    "to_s" => "i.to_s",
    "hash" => "s.hash",
    "native_add" => "i + 1"
  }.freeze

  CSV_FIELDS = %w[kernel engine iterations reps raw_ns net_ns status].freeze
  OVERHEAD_FIELDS = %w[
    kernel rpyyarv_jit_net_ns cruby_net_ns yjit_net_ns
    overhead_vs_cruby_ns ratio_vs_cruby
  ].freeze

  module_function

  def env_for_run
    { LIBVAR => BUILD + File::PATH_SEPARATOR + (ENV[LIBVAR] || "") }
  end

  def driver_source(expr, iterations, reps)
    <<~RUBY
      # frozen_string_literal: true
      s = "abc"
      i = 7
      x = nil
      #{reps}.times do
        start = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        n = 0
        while n < #{iterations}
          #{expr}
          n += 1
        end
        elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - start
        ns = elapsed * 1_000_000_000.0 / #{iterations}
        puts "NS " + ns.to_s
      end
    RUBY
  end

  def timeout_argv(secs, argv)
    ["perl", "-e", "alarm shift; exec @ARGV", secs.to_s] + argv
  end

  def median(values)
    sorted = values.sort
    return nil if sorted.empty?

    middle = sorted.size / 2
    sorted.size.odd? ? sorted[middle] :
      (sorted[middle - 1] + sorted[middle]) / 2.0
  end

  def run_kernel(eargv, script, env, reps, timeout)
    out, err, status = Open3.capture3(
      env, *timeout_argv(timeout, eargv + [script])
    )
    if status.exitstatus == 142
      return [nil, "TIMEOUT"]
    elsif !status.success?
      return [nil, "FAIL: #{err.scrub.lines.last(3).join.strip[0, 200]}"]
    end
    values = out.scan(/^NS (\S+)/).flatten.map(&:to_f)
    return [nil, "FAIL: no NS lines"] if values.size < reps

    [median(values), nil]
  end

  def csv_quote(value)
    text = value.nil? ? "" : value.to_s
    return text unless text.match?(/[",\r\n]/)

    %("#{text.gsub('"', '""')}")
  end

  def write_csv(path, rows, fields)
    File.open(path, "w") do |file|
      file.puts(fields.join(","))
      rows.each do |row|
        file.puts(fields.map { |key| csv_quote(row[key]) }.join(","))
      end
    end
  end

  def resolve_engines(extra)
    (ENGINES + extra).select do |name, eargv|
      if File.executable?(eargv[0])
        true
      else
        puts format("note: skipping %s (%s not found)", name, eargv[0])
        false
      end
    end
  end

  def measure(engines, kernels, iterations, reps, timeout, dir)
    env = env_for_run
    rows = []
    raw_by_engine = Hash.new { |h, k| h[k] = {} }
    kernels.each do |kname, expr|
      script = File.join(dir, "#{kname}.rb")
      File.write(script, driver_source(expr, iterations, reps))
      engines.each do |ename, eargv|
        raw, status = run_kernel(eargv, script, env, reps, timeout)
        raw_by_engine[ename][kname] = raw
        row = { "kernel" => kname, "engine" => ename,
                "iterations" => iterations, "reps" => reps,
                "raw_ns" => raw, "status" => status }
        rows << row
        puts format("%-10s %-12s raw=%s%s", kname, ename,
                     raw ? format("%.2f", raw) : "-",
                     status ? " (#{status})" : "")
      end
    end
    rows.each do |row|
      empty = raw_by_engine[row["engine"]]["empty"]
      row["net_ns"] = row["raw_ns"] - empty if row["raw_ns"] && empty
    end
    [rows, raw_by_engine]
  end

  def overhead_rows(kernels, raw_by_engine)
    kernels.each_key.reject { |k| k == "empty" }.map do |kname|
      empty = { "rpyyarv-jit" => raw_by_engine["rpyyarv-jit"]["empty"],
                "cruby" => raw_by_engine["cruby"]["empty"],
                "cruby+yjit" => raw_by_engine["cruby+yjit"]["empty"] }
      net = {}
      empty.each do |ename, e|
        raw = raw_by_engine[ename][kname]
        net[ename] = raw - e if raw && e
      end
      overhead = net["rpyyarv-jit"] - net["cruby"] if net["rpyyarv-jit"] && net["cruby"]
      ratio = net["rpyyarv-jit"] / net["cruby"] if net["rpyyarv-jit"] && net["cruby"]&.positive?
      { "kernel" => kname, "rpyyarv_jit_net_ns" => net["rpyyarv-jit"],
        "cruby_net_ns" => net["cruby"], "yjit_net_ns" => net["cruby+yjit"],
        "overhead_vs_cruby_ns" => overhead, "ratio_vs_cruby" => ratio }
    end
  end

  def main(argv)
    options = { raw: nil, iterations: 3_000_000, reps: 5, kernels: [],
                extra_engines: [], timeout: 300 }
    parser = OptionParser.new
    parser.on("--raw FILE") { |v| options[:raw] = v }
    parser.on("--iterations N", Integer) { |v| options[:iterations] = v }
    parser.on("--reps N", Integer) { |v| options[:reps] = v }
    parser.on("--kernel NAME") { |v| options[:kernels] << v }
    parser.on("--engine NAME=PATH") do |v|
      name, path = v.split("=", 2)
      abort "usage: --engine NAME=PATH" unless path
      options[:extra_engines] << [name, [File.expand_path(path)]]
    end
    parser.parse!(argv)
    abort "--raw is required" unless options[:raw]

    kernels = if options[:kernels].empty?
                KERNELS
              else
                wanted = (options[:kernels] + ["empty"]).uniq
                KERNELS.select { |k, _| wanted.include?(k) }
              end

    engines = resolve_engines(options[:extra_engines])
    abort "no engines available" if engines.empty?

    output = File.expand_path(options[:raw])
    FileUtils.mkdir_p(File.dirname(output))
    rows = nil
    raw_by_engine = nil
    Dir.mktmpdir("crossing-bench") do |dir|
      rows, raw_by_engine = measure(engines, kernels, options[:iterations],
                                     options[:reps], options[:timeout], dir)
    end

    File.write(output, JSON.pretty_generate(rows) + "\n")
    write_csv(File.join(File.dirname(output), "crossing.csv"), rows, CSV_FIELDS)
    overhead = overhead_rows(kernels, raw_by_engine)
    write_csv(File.join(File.dirname(output), "crossing-overhead.csv"),
              overhead, OVERHEAD_FIELDS)
    0
  end
end

exit CrossingBench.main(ARGV) if $PROGRAM_NAME == __FILE__
