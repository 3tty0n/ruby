#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "json"
require "open3"
require "optparse"
require "tempfile"

module MemoryHarness
  HERE = File.dirname(File.expand_path(__FILE__))
  ROOT = File.expand_path("..", HERE)
  TOP = File.expand_path("..", ROOT)
  BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
  DARWIN = RUBY_PLATFORM.include?("darwin")

  CSV_FIELDS = %w[
    suite benchmark engine peak_rss_bytes peak_rss_mb startup_rss_bytes
    rss_over_startup_mb cruby_heap_live_slots rpython_heap_bytes
    root_mark_walks root_mark_ns status
  ].freeze

  module_function

  def load_bench
    return if defined?(AwfySuite)

    load File.join(ROOT, "scripts", "bench.rb")
  end

  def time_tool_available? = File.executable?("/usr/bin/time")

  def time_wrapper(argv)
    DARWIN ? ["/usr/bin/time", "-l"] + argv : ["/usr/bin/time", "-v"] + argv
  end

  # macOS reports bytes; Linux reports kbytes.
  def parse_peak_rss(err)
    match = DARWIN ? err.match(/(\d+)\s+maximum resident set size/) :
      err.match(/Maximum resident set size \(kbytes\):\s*(\d+)/)
    return nil unless match

    value = match[1].to_i
    DARWIN ? value : value * 1024
  end

  def cruby_engine?(argv) = argv[0] == File.join(BUILD, "ruby")

  # Kept alive via the ivar so its finalizer never deletes the file early.
  def gcstat_prelude
    return @gcstat_prelude.path if @gcstat_prelude

    @gcstat_prelude = Tempfile.new(["memory_gcstat", ".rb"])
    @gcstat_prelude.write(
      'at_exit { $stderr.puts("GCSTAT #{GC.stat[:heap_live_slots]} ' \
      '#{GC.stat[:malloc_increase_bytes]}") }'
    )
    @gcstat_prelude.flush
    @gcstat_prelude.path
  end

  def run_measured(argv, script, env, timeout)
    full = timeout_argv(timeout, time_wrapper(argv) + [script])
    Open3.capture3(env, *full)
  end

  def run_heap(argv, script, env, timeout)
    full = timeout_argv(timeout, argv + ["-r", gcstat_prelude, script])
    _out, err, status = Open3.capture3(env, *full)
    return nil unless status.success?

    match = err[/^GCSTAT (\d+)/, 1]
    match&.to_i
  end

  def fill_measurements(row, argv, script, env, timeout, time_missing)
    if time_missing
      return row.merge!("status" => "UNAVAILABLE")
    end

    _out, err, status = run_measured(argv, script, env, timeout)
    peak = parse_peak_rss(err)
    row["peak_rss_bytes"] = peak
    row["peak_rss_mb"] = peak ? (peak / 1_048_576.0).round(2) : nil
    row["status"] = peak && status.success? ? nil : "UNAVAILABLE"
    if cruby_engine?(argv)
      row["cruby_heap_live_slots"] = run_heap(argv, script, env, timeout)
    else
      row.merge!(run_rpython_report(argv, script, env, timeout))
    end
    row
  end

  # The coverage report is a probe, never the timed run it sits beside.
  def run_rpython_report(argv, script, env, timeout)
    full = timeout_argv(timeout, argv + [script])
    out, err, status = Open3.capture3(
      env.merge("RPYYARV_COVERAGE" => "1"), *full
    )
    return {} unless status.success?

    text = out + err
    { "rpython_heap_bytes" => text[/heap footprint: rpython (\d+)/, 1]&.to_i,
      "root_mark_walks" => text[/root marking: (\d+) walk/, 1]&.to_i,
      "root_mark_ns" => text[/root marking: \d+ walk\(s\), (\d+) ns/, 1]&.to_i }
  end

  def startup_row(ename, eargv, env, time_missing)
    row = { "suite" => "startup", "benchmark" => "__startup__",
            "engine" => ename }
    return row.merge("status" => "MISSING") unless File.executable?(eargv[0])

    Tempfile.create(["memory_empty", ".rb"]) do |file|
      file.write("")
      file.close
      fill_measurements(row, eargv, file.path, env, 60, time_missing)
    end
    row
  end

  def collect(suite, benchmark, ename, eargv, startup_peak, time_missing)
    row = { "suite" => suite.name, "benchmark" => benchmark, "engine" => ename }
    return row.merge("status" => "MISSING") unless File.executable?(eargv[0])

    suite.with_script(benchmark) do |script, env, _warm|
      fill_measurements(row, eargv, script, env, suite.timeout, time_missing)
    end
    peak = row["peak_rss_bytes"]
    if peak && startup_peak
      row["startup_rss_bytes"] = startup_peak
      row["rss_over_startup_mb"] =
        ((peak - startup_peak) / 1_048_576.0).round(2)
    end
    row
  rescue StandardError => error
    row.merge("status" => "ERROR", "error" => "#{error.class}: #{error.message}")
  end

  def csv_quote(value)
    text = value.nil? ? "" : value.to_s
    return text unless text.match?(/[",\r\n]/)

    %("#{text.gsub('"', '""')}")
  end

  def write_csv(path, rows)
    File.open(path, "w") do |file|
      file.puts(CSV_FIELDS.join(","))
      rows.each do |row|
        file.puts(CSV_FIELDS.map { |key| csv_quote(row[key]) }.join(","))
      end
    end
  end

  def main(argv)
    load_bench
    options = { suite: "all", filters: [], extra: [] }
    parser = OptionParser.new
    parser.on("--raw FILE") { |value| options[:raw] = value }
    parser.on("--suite NAME") { |value| options[:suite] = value }
    parser.on("--filter NAME") { |value| options[:filters] << value }
    parser.on("--ruby-bench DIR") { |value| options[:dir] = value }
    parser.on("--warmup N", Integer) { |value| options[:warmup] = value }
    parser.on("--iters N", Integer) { |value| options[:iters] = value }
    parser.on("--engine NAME=PATH") do |value|
      name, path = value.split("=", 2)
      abort "--engine needs NAME=PATH" unless path

      options[:extra] << [name, [File.expand_path(path)]]
    end
    parser.parse!(argv)
    abort "--raw is required" unless options[:raw]

    wanted = case options[:suite]
             when "all" then %w[awfy ruby-bench]
             when "awfy" then %w[awfy]
             when "ruby-bench", "yjit-bench" then %w[ruby-bench]
             else abort "unknown suite: #{options[:suite]}"
             end

    engines = BASE_ENGINES + options[:extra]
    output = File.expand_path(options[:raw])
    FileUtils.mkdir_p(File.dirname(output))
    time_missing = !time_tool_available?
    env = base_env

    rows = []
    startup = {}
    engines.each do |ename, eargv|
      puts "memory: startup/#{ename}"
      row = startup_row(ename, eargv, env, time_missing)
      startup[ename] = row["peak_rss_bytes"]
      rows << row
      File.write(output, JSON.pretty_generate(rows) + "\n")
    end

    wanted.each do |name|
      suite = name == "awfy" ? AwfySuite.new(options) : RubyBenchSuite.new(options)
      next unless suite.available?

      names = suite.benchmarks.select do |benchmark|
        options[:filters].empty? ||
          options[:filters].any? { |filter| benchmark.include?(filter) }
      end
      names.each do |benchmark|
        puts "memory: #{suite.name}/#{benchmark}"
        engines.each do |ename, eargv|
          row = collect(suite, benchmark, ename, eargv, startup[ename],
                        time_missing)
          rows << row
          File.write(output, JSON.pretty_generate(rows) + "\n")
        end
      end
    end

    File.write(output, JSON.pretty_generate(rows) + "\n")
    write_csv(File.join(File.dirname(output), "memory.csv"), rows)
    0
  end
end

exit MemoryHarness.main(ARGV) if $PROGRAM_NAME == __FILE__
