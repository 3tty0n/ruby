#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "json"
require "open3"
require "optparse"

module MechanismHarness
  HERE = File.dirname(File.expand_path(__FILE__))
  ROOT = File.expand_path("..", HERE)
  TOP = File.expand_path("..", ROOT)
  BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
  SUMMARY_INTS = {
    "ops" => "ops",
    "recorded ops" => "recorded_ops",
    "calls" => "recorded_calls",
    "guards" => "guards",
    "opt ops" => "opt_ops",
    "opt guards" => "opt_guards",
    "forcings" => "forcings",
    "abort: trace too long" => "abort_trace_too_long",
    "abort: compiling" => "abort_compiling",
    "abort: vable escape" => "abort_vable_escape",
    "abort: bad loop" => "abort_bad_loop",
    "abort: force quasi-immut" => "abort_force_quasiimmut",
    "abort: segmenting trace" => "abort_segmenting_trace",
    "virtualizables forced" => "virtualizables_forced",
    "nvirtuals" => "nvirtuals",
    "Total # of loops" => "loops",
    "Total # of bridges" => "bridges",
    "Freed # of loops" => "freed_loops",
    "Freed # of bridges" => "freed_bridges"
  }.freeze

  CSV_FIELDS = %w[
    suite benchmark status median_ms loops bridges bridges_per_loop
    live_loops live_bridges bridge_freed_share tracing_s backend_s total_s
    compile_fraction opt_ops opt_guards guards_per_opt_op recorded_calls
    residual_calls_per_opt_op compiled_trace_body_bytes loop_trace_body_bytes
    bridge_trace_body_bytes aborts files_native files_delegated
    iseqs_native iseqs_total native_sends cruby_sends cruby_send_share
    cruby_sends_per_iteration
    yjit_ratio_in_jit yjit_side_exits yjit_compiled_iseqs
    yjit_side_exits_per_kinstruction yjit_versions_per_block yjit_code_size
    yjit_invalidation_count yjit_compile_time_ms zjit_ratio_in_jit
    zjit_side_exits zjit_compiled_iseqs zjit_side_exits_per_kinstruction
    zjit_code_size zjit_compile_time_ms zjit_invalidation_time_ms
    zjit_dynamic_send_share performance_jit_over_yjit
  ].freeze

  module_function

  def load_bench
    return if defined?(AwfySuite)

    load File.join(ROOT, "scripts", "bench.rb")
  end

  def median(values)
    sorted = values.sort
    return nil if sorted.empty?

    middle = sorted.size / 2
    sorted.size.odd? ? sorted[middle] :
      (sorted[middle - 1] + sorted[middle]) / 2.0
  end

  def run_child(argv, script, env, timeout)
    out, err, status = Open3.capture3(
      env, *timeout_argv(timeout, argv + [script])
    )
    [out.scrub, err.scrub, status]
  end

  def parse_times(out)
    times = out.scan(/^ITER \d+ (\S+)/).flatten.map(&:to_f)
    warmed = out[/^WARMED (\d+)/, 1]
    warm = warmed ? warmed.to_i : 0
    median(times[warm..] || times)
  end

  def parse_summary(text)
    row = {}
    if text =~ /^Tracing:\s+(\d+)\s+([\d.]+)/
      row["traces"] = Regexp.last_match(1).to_i
      row["tracing_s"] = Regexp.last_match(2).to_f
    end
    if text =~ /^Backend:\s+(\d+)\s+([\d.]+)/
      row["backend_runs"] = Regexp.last_match(1).to_i
      row["backend_s"] = Regexp.last_match(2).to_f
    end
    row["total_s"] = Regexp.last_match(1).to_f if text =~ /^TOTAL:\s+([\d.]+)/
    SUMMARY_INTS.each do |printed, key|
      match = text.match(/^\s*#{Regexp.escape(printed)}:\s+(\d+)/)
      row[key] = match[1].to_i if match
    end
    loop_ranges = text.scan(
      /^Loop .* has address 0x([0-9a-f]+) to 0x([0-9a-f]+)/i
    )
    bridge_ranges = text.scan(
      /^bridge .* has address 0x([0-9a-f]+) to 0x([0-9a-f]+)/i
    )
    row["loop_trace_body_bytes"] = range_bytes(loop_ranges)
    row["bridge_trace_body_bytes"] = range_bytes(bridge_ranges)
    row["compiled_trace_body_bytes"] =
      row["loop_trace_body_bytes"] + row["bridge_trace_body_bytes"]
    derive_summary(row)
    row
  end

  def range_bytes(ranges)
    ranges.sum { |start, stop| stop.to_i(16) - start.to_i(16) }
  end

  def derive_summary(row)
    loops = row["loops"].to_i
    bridges = row["bridges"].to_i
    row["bridges_per_loop"] = bridges.to_f / loops if loops.positive?
    row["live_loops"] = loops - row["freed_loops"].to_i
    row["live_bridges"] = bridges - row["freed_bridges"].to_i
    if bridges.positive?
      row["bridge_freed_share"] = row["freed_bridges"].to_f / bridges
    end
    total = row["total_s"].to_f
    if total.positive?
      row["compile_fraction"] =
        (row["tracing_s"].to_f + row["backend_s"].to_f) / total
    end
    ops = row["opt_ops"].to_i
    if ops.positive?
      row["guards_per_opt_op"] = row["opt_guards"].to_f / ops
      row["residual_calls_per_opt_op"] =
        row["recorded_calls"].to_f / ops
    end
    row["aborts"] = SUMMARY_INTS.values.grep(/^abort_/).sum do |key|
      row[key].to_i
    end
  end

  def parse_coverage(text)
    row = {}
    if text =~ /sends: rpyyarv (\d+), cruby (\d+)/
      row["native_sends"] = Regexp.last_match(1).to_i
      row["cruby_sends"] = Regexp.last_match(2).to_i
      total = row["native_sends"] + row["cruby_sends"]
      row["cruby_send_share"] = row["cruby_sends"].to_f / total if total.positive?
      row["cruby_sends_per_iteration"] = row["cruby_sends"]
    end
    if text =~ /files: rpyyarv (\d+), delegated to cruby (\d+)/
      row["files_native"] = Regexp.last_match(1).to_i
      row["files_delegated"] = Regexp.last_match(2).to_i
    end
    if text =~ /iseqs: (\d+)\/(\d+)/
      row["iseqs_native"] = Regexp.last_match(1).to_i
      row["iseqs_total"] = Regexp.last_match(2).to_i
    end
    row["top_cruby_sends"] = text.scan(
      /\[rpyyarv\]\s+cruby send: (.*?) (\d+)$/
    ).map { |name, count| { "name" => name, "count" => count.to_i } }
    row
  end

  def parse_vm_stats(text, prefix)
    stats = {}
    text.each_line do |line|
      match = line.match(/^\s*([a-zA-Z][\w]+):\s+([\d,]+(?:\.\d+)?)(%)?/)
      next unless match

      number = match[2].delete(",")
      value = number.include?(".") ? number.to_f : number.to_i
      value = value.to_f / 100.0 if match[3]
      if match[1].start_with?("ratio_in_") && value > 1
        value = value.to_f / 100.0
      end
      stats[match[1]] = value
    end
    code_size = %w[inline_code_size outlined_code_size].sum do |key|
      stats[key].to_i
    end
    code_size = stats["code_region_bytes"].to_i unless code_size.positive?
    side_exits = stats["side_exit_count"]
    instructions = stats["total_insns_count"]
    instructions ||= stats["total_insn_count"]
    exit_density = if side_exits && instructions && instructions.positive?
                     1000.0 * side_exits / instructions
                   end
    block_ids = stats["compiled_blockid_count"]
    blocks = stats["compiled_block_count"]
    versions = if blocks && block_ids && block_ids.positive?
                 blocks.to_f / block_ids
               end
    compile_time_ms = stats["compile_time_ms"]
    compile_time_ms ||= stats["compile_time_ns"].to_f / 1_000_000.0 if
      stats["compile_time_ns"]
    invalidation_time_ms = stats["invalidation_time_ns"].to_f / 1_000_000.0 if
      stats["invalidation_time_ns"]
    sends = stats["send_count"]
    dynamic_send_share = if sends && sends.positive?
                           stats["dynamic_send_count"].to_f / sends
                         end
    {
      "#{prefix}_ratio_in_jit" =>
        stats["ratio_in_#{prefix}"],
      "#{prefix}_side_exits" => stats["side_exit_count"],
      "#{prefix}_compiled_iseqs" => stats["compiled_iseq_count"],
      "#{prefix}_side_exits_per_kinstruction" => exit_density,
      "#{prefix}_versions_per_block" => versions,
      "#{prefix}_code_size" => code_size.positive? ? code_size : nil,
      "#{prefix}_invalidation_count" => stats["invalidation_count"],
      "#{prefix}_compile_time_ms" => compile_time_ms,
      "#{prefix}_invalidation_time_ms" => invalidation_time_ms,
      "#{prefix}_dynamic_send_share" => dynamic_send_share,
      "#{prefix}_stats" => stats
    }
  end

  def safe_name(suite, benchmark)
    "#{suite}-#{benchmark}".gsub(/[^A-Za-z0-9_.-]/, "_")
  end

  def rpy_summary(suite, benchmark, script, env, warm, log_dir)
    log = File.join(log_dir, "#{safe_name(suite.name, benchmark)}.jit-summary")
    categories = "jit-summary,jit-backend-addr"
    child_env = env.merge("PYPYLOG" => "#{categories}:#{log}",
                          "RPYYARV_COVERAGE" => nil)
    argv = [File.join(ROOT, "rpyyarv-jit")]
    out, err, status = run_child(argv, script, child_env, suite.timeout)
    row = { "status" => status.success? ? nil : "FAIL",
            "median_ms" => parse_times(out), "warmup_iterations" => warm,
            "stderr" => err.lines.last(20).join }
    row.merge!(parse_summary(File.exist?(log) ? File.read(log) : ""))
    row
  end

  def vm_stats(suite, script, env, engine, flag, prefix)
    argv = [File.join(BUILD, "ruby"), "--disable-gems", engine, flag]
    out, err, status = run_child(argv, script,
                                 env.merge("PYPYLOG" => nil), suite.timeout)
    row = parse_vm_stats(out + err, prefix)
    row["#{prefix}_status"] = status.success? ? nil : "UNAVAILABLE"
    row
  end

  def coverage(suite, benchmark)
    row = {}
    suite.with_script(benchmark, probe: true) do |script, env, _warm|
      argv = [File.join(ROOT, "rpyyarv")]
      out, err, status = run_child(
        argv, script, env.merge("RPYYARV_COVERAGE" => "1",
                                "PYPYLOG" => nil), suite.timeout
      )
      row = parse_coverage(out + err)
      row["coverage_status"] = status.success? ? nil : "FAIL"
    end
    row
  end

  def performance_ratios(path)
    return {} unless path

    raw = JSON.parse(File.read(path))
    grouped = Hash.new { |hash, key| hash[key] = {} }
    raw.each do |key, value|
      suite, benchmark, engine = key.split("/", 3)
      grouped[[suite, benchmark]][engine] = value["median"]
    end
    grouped.each_with_object({}) do |(key, engines), ratios|
      jit = engines["rpyyarv-jit"]
      yjit = engines["cruby+yjit"]
      ratios[key] = jit.to_f / yjit if jit && yjit && yjit.positive?
    end
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

  def collect(suite, benchmark, log_dir, ratios)
    row = { "suite" => suite.name, "benchmark" => benchmark }
    suite.with_script(benchmark) do |script, env, warm|
      row.merge!(rpy_summary(suite, benchmark, script, env, warm, log_dir))
      row.merge!(vm_stats(suite, script, env, "--yjit", "--yjit-stats",
                          "yjit"))
      row.merge!(vm_stats(suite, script, env, "--zjit", "--zjit-stats",
                          "zjit"))
    end
    row.merge!(coverage(suite, benchmark))
    row["performance_jit_over_yjit"] = ratios[[suite.name, benchmark]]
    row
  rescue StandardError => error
    row.merge("status" => "ERROR",
              "error" => "#{error.class}: #{error.message}")
  end

  def main(argv)
    load_bench
    options = { suite: "all", filters: [], raw: nil, performance: nil }
    parser = OptionParser.new
    parser.on("--suite NAME") { |value| options[:suite] = value }
    parser.on("--filter NAME") { |value| options[:filters] << value }
    parser.on("--raw FILE") { |value| options[:raw] = value }
    parser.on("--performance FILE") { |value| options[:performance] = value }
    parser.on("--ruby-bench DIR") { |value| options[:dir] = value }
    parser.on("--warmup N", Integer) { |value| options[:warmup] = value }
    parser.on("--iters N", Integer) { |value| options[:iters] = value }
    parser.parse!(argv)
    abort "--raw is required" unless options[:raw]

    wanted = case options[:suite]
             when "all" then %w[awfy ruby-bench]
             when "awfy" then %w[awfy]
             when "ruby-bench", "yjit-bench" then %w[ruby-bench]
             else abort "unknown suite: #{options[:suite]}"
             end
    output = File.expand_path(options[:raw])
    log_dir = File.join(File.dirname(output), "jit-logs")
    FileUtils.mkdir_p(log_dir)
    ratios = performance_ratios(options[:performance])
    rows = []
    wanted.each do |name|
      suite = name == "awfy" ? AwfySuite.new(options) : RubyBenchSuite.new(options)
      next unless suite.available?

      names = suite.benchmarks.select do |benchmark|
        options[:filters].empty? ||
          options[:filters].any? { |filter| benchmark.include?(filter) }
      end
      names.each do |benchmark|
        puts "mechanisms: #{suite.name}/#{benchmark}"
        row = collect(suite, benchmark, log_dir, ratios)
        rows << row
        File.write(output, JSON.pretty_generate(rows) + "\n")
      end
    end
    File.write(output, JSON.pretty_generate(rows) + "\n")
    write_csv(File.join(File.dirname(output), "mechanisms.csv"), rows)
    0
  end
end

exit MechanismHarness.main(ARGV) if $PROGRAM_NAME == __FILE__
