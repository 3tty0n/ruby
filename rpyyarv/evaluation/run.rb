#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "json"
require "open3"
require "optparse"
require "rbconfig"
require "time"

require_relative "experiments"

module RPyYARVEvaluation
  ROOT = File.expand_path("..", __dir__)
  TOP = File.expand_path("..", ROOT)
  DEFAULT_RESULTS = File.join(__dir__, "results")

  module_function

  def capture(*argv, chdir: ROOT)
    out, status = Open3.capture2e(*argv, chdir: chdir)
    [out.strip, status.success?]
  end

  def git_metadata
    commit, = capture("git", "rev-parse", "HEAD", chdir: TOP)
    status, = capture("git", "status", "--porcelain=v1", chdir: TOP)
    { "commit" => commit, "dirty" => !status.empty?,
      "changed_paths" => status.lines.map(&:strip) }
  end

  def host_metadata
    uname, = capture("uname", "-a")
    { "ruby" => RUBY_DESCRIPTION, "platform" => RUBY_PLATFORM,
      "uname" => uname }
  end

  def run_id(kind)
    stamp = Time.now.utc.strftime("%Y%m%dT%H%M%SZ")
    "#{stamp}-#{kind}-#{Process.pid}"
  end

  def write_json(path, value)
    tmp = "#{path}.tmp-#{Process.pid}"
    File.write(tmp, JSON.pretty_generate(value) + "\n")
    File.rename(tmp, path)
  ensure
    File.unlink(tmp) if tmp && File.exist?(tmp)
  end

  module Csv
    module_function

    def write(path, headers, rows)
      File.open(path, "w") do |file|
        file.puts(headers.map { |value| quote(value) }.join(","))
        rows.each do |row|
          values = row.is_a?(Hash) ? headers.map { |key| row[key] } : row
          file.puts(values.map { |value| quote(value) }.join(","))
        end
      end
    end

    def quote(value)
      text = value.nil? ? "" : value.to_s
      return text unless text.match?(/[",\r\n]/)

      %("#{text.gsub('"', '""')}")
    end
  end

  class Run
    attr_reader :dir, :manifest

    def initialize(kind, results_root)
      @dir = File.join(File.expand_path(results_root),
                       RPyYARVEvaluation.run_id(kind))
      FileUtils.mkdir_p(@dir)
      @manifest = {
        "schema" => 1,
        "kind" => kind,
        "started_at" => Time.now.utc.iso8601,
        "git" => RPyYARVEvaluation.git_metadata,
        "host" => RPyYARVEvaluation.host_metadata,
        "commands" => []
      }
      save
    end

    def execute(name, env, argv, chdir: ROOT)
      log_path = File.join(@dir, "#{name}.log")
      started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      status = nil
      File.open(log_path, "w") do |log|
        Open3.popen2e(env, *argv, chdir: chdir) do |_stdin, output, wait|
          output.each do |line|
            log.write(line)
            $stdout.write(line)
          end
          status = wait.value
        end
      end
      elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
      @manifest["commands"] << {
        "name" => name, "argv" => argv, "environment" => env,
        "exit_status" => status.exitstatus, "seconds" => elapsed,
        "log" => File.basename(log_path)
      }
      save
      status.success?
    rescue Interrupt
      @manifest["interrupted"] = true
      save
      raise
    end

    def finish(ok)
      @manifest["finished_at"] = Time.now.utc.iso8601
      @manifest["success"] = ok
      save
    end

    private

    def save
      RPyYARVEvaluation.write_json(File.join(@dir, "manifest.json"),
                                   @manifest)
    end
  end

  module Analyzer
    module_function

    def analyze(raw_path, out_dir)
      raw = JSON.parse(File.read(raw_path))
      rows = raw.map { |key, value| row_for(key, value) }
      FileUtils.mkdir_p(out_dir)
      write_measurements(File.join(out_dir, "measurements.csv"), rows)
      ratios = ratio_rows(rows)
      write_ratios(File.join(out_dir, "ratios.csv"), ratios)
      summary = summarize(ratios)
      write_summary(File.join(out_dir, "summary.csv"), summary)
      { "measurements" => rows.size, "ratios" => ratios.size,
        "summary" => summary }
    end

    def row_for(key, value)
      suite, benchmark, engine = key.split("/", 3)
      info = value["info"] || {}
      {
        "suite" => suite, "benchmark" => benchmark, "engine" => engine,
        "status" => value["status"], "median_ms" => value["median"],
        "min_ms" => value["min"], "samples" => value["n"],
        "spread" => value["spread"], "iseqs" => info["iseqs"],
        "files_native" => info["files_native"],
        "files_delegated" => info["files_delegated"]
      }
    end

    def ratio_rows(rows)
      grouped = rows.group_by { |r| [r["suite"], r["benchmark"]] }
      grouped.each_with_object([]) do |((suite, benchmark), group), result|
        by_engine = group.to_h { |r| [r["engine"], r] }
        jit = numeric(by_engine.dig("rpyyarv-jit", "median_ms"))
        yjit = numeric(by_engine.dig("cruby+yjit", "median_ms"))
        cruby = numeric(by_engine.dig("cruby", "median_ms"))
        next unless jit

        result << { "suite" => suite, "benchmark" => benchmark,
                    "rpyyarv_jit_over_yjit" => yjit && jit / yjit,
                    "rpyyarv_jit_over_cruby" => cruby && jit / cruby }
      end
    end

    def numeric(value)
      value.is_a?(Numeric) && value.positive? ? value.to_f : nil
    end

    def geomean(values)
      vals = values.compact
      return nil if vals.empty?

      Math.exp(vals.sum { |v| Math.log(v) } / vals.size)
    end

    def summarize(ratios)
      groups = ratios.group_by { |r| r["suite"] }
      groups["all"] = ratios
      groups.map do |suite, group|
        yjit = group.map { |r| r["rpyyarv_jit_over_yjit"] }.compact
        cruby = group.map { |r| r["rpyyarv_jit_over_cruby"] }.compact
        { "suite" => suite, "n_yjit" => yjit.size,
          "n_cruby" => cruby.size,
          "geomean_jit_over_yjit" =>
            geomean(yjit),
          "geomean_jit_over_cruby" =>
            geomean(cruby) }
      end
    end

    def write_measurements(path, rows)
      headers = %w[suite benchmark engine status median_ms min_ms samples
                   spread iseqs files_native files_delegated]
      write_csv(path, headers, rows)
    end

    def write_ratios(path, rows)
      headers = %w[suite benchmark rpyyarv_jit_over_yjit
                   rpyyarv_jit_over_cruby]
      write_csv(path, headers, rows)
    end

    def write_summary(path, rows)
      headers = %w[suite n_yjit n_cruby geomean_jit_over_yjit
                   geomean_jit_over_cruby]
      write_csv(path, headers, rows)
    end

    def write_csv(path, headers, rows)
      Csv.write(path, headers, rows)
    end
  end

  module Boundary
    module_function

    def extract(log_path, csv_path)
      lines = File.readlines(log_path, chomp: true)
      rows = lines.each_with_object([]) do |line, all|
        match = line.match(/\A(\S+)\s+sends: rpyyarv (\d+), cruby (\d+)/)
        next unless match

        native = match[2].to_i
        cruby = match[3].to_i
        total = native + cruby
        all << [match[1], native, cruby, total,
                total.zero? ? nil : cruby.to_f / total]
      end
      headers = %w[benchmark rpyyarv_sends cruby_sends total_sends cruby_share]
      Csv.write(csv_path, headers, rows)
      rows.size
    end
  end

  module Loc
    module_function

    def collect
      files, ok = RPyYARVEvaluation.capture("git", "ls-files", "rpyyarv",
                                            chdir: TOP)
      raise "git ls-files failed" unless ok

      counts = Hash.new { |hash, key| hash[key] = [0, 0] }
      files.lines.map(&:strip).each do |repo_path|
        relative = repo_path.delete_prefix("rpyyarv/")
        category = classify(relative)
        next unless category

        path = File.join(TOP, repo_path)
        next unless File.file?(path)

        counts[category][0] += 1
        counts[category][1] += File.foreach(path).count
      end
      counts
    end

    def classify(relative)
      EvaluationConfig::LOC_CATEGORIES.each do |category, patterns|
        return category if patterns.any? do |pattern|
          File.fnmatch?(pattern, relative, File::FNM_PATHNAME)
        end
      end
      nil
    end
  end

  def base_env
    { "RPYYARV_BUILD" => ENV.fetch("RPYYARV_BUILD",
                                    File.join(TOP, "build")) }
  end

  def performance(args, results_root)
    run = Run.new("performance", results_root)
    raw = File.join(run.dir, "raw.json")
    argv = [RbConfig.ruby, File.join(ROOT, "scripts", "bench.rb"),
            "--raw", raw] + args
    ok = run.execute("performance", base_env, argv)
    Analyzer.analyze(raw, run.dir) if File.exist?(raw)
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def boundary(args, results_root)
    run = Run.new("boundary", results_root)
    argv = [RbConfig.ruby, File.join(ROOT, "scripts", "bench.rb"),
            "--foreign=20"] + args
    ok = run.execute("boundary", base_env, argv)
    log = File.join(run.dir, "boundary.log")
    count = Boundary.extract(log, File.join(run.dir, "boundary.csv"))
    run.manifest["boundary_rows"] = count
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def gc_sweep(args, results_root)
    limits = if args.empty?
               EvaluationConfig::GC_LIMITS
             else
               args.map { |value| Integer(value) }
             end
    run = Run.new("gc", results_root)
    outcomes = limits.map do |limit|
      argv = ["make", "gccheck", "GCLIMIT=#{limit}"]
      run.execute("gc-#{limit}", base_env, argv, chdir: ROOT)
    end
    ok = outcomes.all?
    run.manifest["gc_limits"] = limits
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def doctor
    rows = {
      "repository" => TOP,
      "ruby" => RbConfig.ruby,
      "bench driver" => File.join(ROOT, "scripts", "bench.rb"),
      "cruby" => File.join(TOP, "build", "ruby"),
      "rpyyarv" => File.join(ROOT, "rpyyarv"),
      "rpyyarv-jit" => File.join(ROOT, "rpyyarv-jit"),
      "rebench (optional)" => ENV.fetch("PATH", "").split(File::PATH_SEPARATOR)
                                  .map { |dir| File.join(dir, "rebench") }
                                  .find { |path| File.executable?(path) }
    }
    rows.each do |name, path|
      state = path && File.exist?(path) ? "ok" : "missing"
      puts format("%-20s %-7s %s", name, state, path || "-")
    end
    required = rows.reject { |name, _path| name.include?("optional") }
    required.values.compact.all? { |path| File.exist?(path) } ? 0 : 1
  end

  def loc(out_path)
    rows = Loc.collect.sort.map do |category, (files, lines)|
      { "category" => category, "files" => files, "physical_lines" => lines }
    end
    FileUtils.mkdir_p(File.dirname(File.expand_path(out_path)))
    Csv.write(out_path, %w[category files physical_lines], rows)
    puts "wrote #{out_path}"
    0
  end

  def usage
    <<~TEXT
      usage: evaluation/run.rb [--results DIR] COMMAND [ARGS]

      commands:
        doctor                   check binaries without running benchmarks
        performance [BENCH-ARGS] run the five-engine steady-state experiment
        boundary [BENCH-ARGS]    run the non-timing delegation census
        gc [LIMIT ...]           run gccheck at each malloc limit
        analyze RAW [OUT-DIR]    convert bench.rb JSON to tidy CSV
        loc [OUT.csv]            count the categorized implementation surface

      BENCH-ARGS are passed unchanged to scripts/bench.rb. Examples include
      --suite, --filter, --procs, --warmup, and --iters.
    TEXT
  end

  def main(argv)
    results_root = ENV.fetch("RPYYARV_EVAL_RESULTS", DEFAULT_RESULTS)
    parser = OptionParser.new
    parser.banner = usage
    parser.on("--results DIR") { |dir| results_root = dir }
    parser.order!(argv)
    command = argv.shift
    case command
    when "doctor" then doctor
    when "performance" then performance(argv, results_root)
    when "boundary" then boundary(argv, results_root)
    when "gc" then gc_sweep(argv, results_root)
    when "analyze"
      raw = argv.shift or abort usage
      out = argv.shift || File.dirname(File.expand_path(raw))
      puts JSON.pretty_generate(Analyzer.analyze(raw, out))
      0
    when "loc"
      loc(argv.shift || File.join(DEFAULT_RESULTS, "implementation-loc.csv"))
    else
      warn usage
      command ? 2 : 0
    end
  end
end

exit RPyYARVEvaluation.main(ARGV) if $PROGRAM_NAME == __FILE__
