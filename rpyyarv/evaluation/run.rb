#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "digest"
require "json"
require "open3"
require "optparse"
require "rbconfig"
require "time"

require_relative "experiments"
require_relative "plots"

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
      comparisons = comparison_rows(rows)
      write_comparisons(File.join(out_dir, "comparisons.csv"), comparisons)
      warmup = warmup_rows(raw)
      write_warmup(File.join(out_dir, "warmup.csv"), warmup)
      summary = summarize(ratios)
      summary = attach_status_counts(summary, rows)
      write_summary(File.join(out_dir, "summary.csv"), summary)
      { "measurements" => rows.size, "ratios" => ratios.size,
        "comparisons" => comparisons.size, "warmup_processes" => warmup.size,
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
        next unless jit

        row = { "suite" => suite, "benchmark" => benchmark }
        EvaluationConfig::REFERENCES.each do |label, engine|
          reference = numeric(by_engine.dig(engine, "median_ms"))
          row["rpyyarv_jit_over_#{label}"] = reference && jit / reference
        end
        result << row
      end
    end

    def numeric(value)
      value.is_a?(Numeric) && value.positive? ? value.to_f : nil
    end

    def comparison_rows(rows)
      grouped = rows.group_by { |r| [r["suite"], r["benchmark"]] }
      grouped.each_with_object([]) do |((suite, benchmark), group), result|
        by_engine = group.to_h { |row| [row["engine"], row] }
        baseline = numeric(by_engine.dig("rpyyarv-jit", "median_ms"))
        next unless baseline

        by_engine.each do |engine, row|
          next if engine == "rpyyarv-jit"

          time = numeric(row["median_ms"])
          next unless time

          result << {
            "suite" => suite, "benchmark" => benchmark,
            "engine" => engine,
            "engine_over_rpyyarv_jit" => time / baseline
          }
        end
      end
    end

    def warmup_rows(raw)
      raw.each_with_object([]) do |(key, value), rows|
        suite, benchmark, engine = key.split("/", 3)
        iterations = value["raw_iterations"] || []
        warmed = value["warmed_at"] || []
        iterations.each_with_index do |samples, process|
          steady = samples[(warmed[process] || 0)..] || []
          center = median_value(steady)
          stable = stable_iteration(samples, center)
          rows << {
            "suite" => suite, "benchmark" => benchmark,
            "engine" => engine, "process" => process,
            "harness_warmed_at" => warmed[process],
            "stable_iteration" => stable,
            "time_to_stable_ms" =>
              stable && samples[0..stable].sum,
            "steady_median_ms" => center
          }
        end
      end
    end

    def median_value(values)
      sorted = values.compact.sort
      return nil if sorted.empty?

      middle = sorted.size / 2
      sorted.size.odd? ? sorted[middle] :
        (sorted[middle - 1] + sorted[middle]) / 2.0
    end

    def stable_iteration(samples, center, tolerance = 0.10, window = 5)
      return nil unless center && center.positive?
      return nil if samples.size < window

      limit = center * tolerance
      (0..samples.size - window).find do |index|
        samples[index, window].all? { |value| (value - center).abs <= limit }
      end
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
        row = { "suite" => suite }
        EvaluationConfig::REFERENCES.each_key do |label|
          values = group.map do |ratio|
            ratio["rpyyarv_jit_over_#{label}"]
          end.compact
          row["n_#{label}"] = values.size
          row["geomean_jit_over_#{label}"] = geomean(values)
        end
        row
      end
    end

    # A geomean over survivors only is a lie without the excluded counts.
    def attach_status_counts(summary, rows)
      jit = rows.select { |row| row["engine"] == "rpyyarv-jit" }
      summary.map do |entry|
        group = entry["suite"] == "all" ? jit :
                  jit.select { |row| row["suite"] == entry["suite"] }
        entry.merge(
          "n_benchmarks" => group.size,
          "n_ok" => group.count { |row| row["status"].nil? || row["status"] == "" },
          "n_delegated" => group.count { |row| row["status"].to_s == "DELEGATED" },
          "n_failed" => group.count do |row|
            !row["status"].to_s.empty? && row["status"].to_s != "DELEGATED"
          end
        )
      end
    end

    def write_measurements(path, rows)
      headers = %w[suite benchmark engine status median_ms min_ms samples
                   spread iseqs files_native files_delegated]
      write_csv(path, headers, rows)
    end

    def write_ratios(path, rows)
      headers = %w[suite benchmark] + EvaluationConfig::REFERENCES.keys.map do |label|
        "rpyyarv_jit_over_#{label}"
      end
      write_csv(path, headers, rows)
    end

    def write_summary(path, rows)
      headers = ["suite"]
      EvaluationConfig::REFERENCES.each_key do |label|
        headers << "n_#{label}"
        headers << "geomean_jit_over_#{label}"
      end
      headers += %w[n_benchmarks n_ok n_delegated n_failed]
      write_csv(path, headers, rows)
    end

    def write_comparisons(path, rows)
      headers = %w[suite benchmark engine engine_over_rpyyarv_jit]
      write_csv(path, headers, rows)
    end

    def write_warmup(path, rows)
      headers = %w[suite benchmark engine process harness_warmed_at
                   stable_iteration time_to_stable_ms steady_median_ms]
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

    # The --foreign probe runs one iteration, so its counts are per-iteration.
    def reasons(log_path)
      benchmark = nil
      File.readlines(log_path, chomp: true).each_with_object([]) do |line, all|
        if (head = line.match(/\A(\S+)\s+sends: rpyyarv (\d+), cruby (\d+)/))
          benchmark = head[1]
          next
        end
        tail = line.match(/\A\s+(\d+) file\(s\): (.*)\z/)
        all << [benchmark, tail[1].to_i, tail[2]] if benchmark && tail
      end
    end

    def classify(reason)
      return nil if reason.to_s.empty?

      EvaluationConfig::DELEGATION_CLASSES.each do |pattern, label|
        return label if pattern.match?(reason.to_s)
      end
      nil
    end

    def coverage(log_path, inventory, csv_path)
      sends = File.readlines(log_path, chomp: true).each_with_object({}) do |line, all|
        match = line.match(/\A(\S+)\s+sends: rpyyarv (\d+), cruby (\d+)/)
        all[match[1]] = [match[2].to_i, match[3].to_i] if match
      end
      grouped = reasons(log_path).group_by(&:first)
      rows = (sends.keys | inventory.keys).sort.map do |bench|
        native, cruby = sends[bench] || [nil, nil]
        entry = inventory[bench] || {}
        top = (grouped[bench] || []).max_by { |row| row[1] }
        total = native.to_i + cruby.to_i
        { "benchmark" => bench, "status" => entry["status"],
          "iseqs" => entry["iseqs"], "why" => entry["why"],
          "rpyyarv_sends" => native, "cruby_sends_per_iteration" => cruby,
          "cruby_send_share" => total.zero? ? nil : cruby.to_f / total,
          "delegated_files" => top && top[1], "top_reason" => top && top[2],
          "class_hint" => classify(top ? top[2] : entry["why"]) }
      end
      headers = %w[benchmark status iseqs why rpyyarv_sends
                   cruby_sends_per_iteration cruby_send_share delegated_files
                   top_reason class_hint]
      Csv.write(csv_path, headers, rows)
      rows
    end
  end

  # Turns any CSV this harness writes into an org table for the paper draft.
  module Org
    module_function

    def render(csv_path)
      rows = File.readlines(csv_path, chomp: true).reject(&:empty?)
      return "" if rows.empty?

      cells = rows.map { |line| split(line) }
      body = cells.map { |row| "| #{row.join(' | ')} |" }
      ([body.first, "|---"] + body[1..]).join("\n")
    end

    def split(line)
      line.scan(/(?:\A|,)(?:"((?:[^"]|"")*)"|([^,]*))/).map do |quoted, plain|
        (quoted ? quoted.gsub('""', '"') : plain).to_s
      end
    end

    def write(out_dir, org_path)
      sections = Dir[File.join(out_dir, "*.csv")].sort.map do |csv|
        "** #{File.basename(csv, '.csv')}\n\n#{render(csv)}\n"
      end
      File.write(org_path, "* #{File.basename(out_dir)}\n\n#{sections.join("\n")}")
      org_path
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

  def build_dir
    ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
  end

  def library_path_var
    RUBY_PLATFORM.include?("darwin") ? "DYLD_LIBRARY_PATH" : "LD_LIBRARY_PATH"
  end

  def arch_dir
    Dir[File.join(build_dir, ".ext", "include", "*", "ruby", "config.h")]
      .sort.first&.then { |path| File.dirname(File.dirname(path)) }
  end

  def uninstalled_rubylib
    build = build_dir
    arch = arch_dir
    paths = [File.join(TOP, "lib"), File.join(build, ".ext", "common"), build]
    paths << File.join(build, ".ext", File.basename(arch)) if arch
    paths.join(File::PATH_SEPARATOR)
  end

  def base_env
    build = build_dir
    inherited = ENV[library_path_var].to_s.split(File::PATH_SEPARATOR)
    path = ([build] + inherited).reject(&:empty?).uniq
                                .join(File::PATH_SEPARATOR)
    { "RPYYARV_BUILD" => build, library_path_var => path,
      "RUBYLIB" => ENV.fetch("RUBYLIB") { uninstalled_rubylib },
      "AWFY_RUBYLIB" => ENV.fetch("AWFY_RUBYLIB") { File.join(TOP, "lib") } }
  end

  # RbConfig.ruby names the install prefix, which an uninstalled build lacks.
  def driver_ruby
    built = File.join(build_dir, "ruby")
    File.executable?(built) ? built : RbConfig.ruby
  end

  def find_command(name)
    ENV.fetch("PATH", "").split(File::PATH_SEPARATOR).each do |dir|
      path = File.join(dir, name)
      return path if File.executable?(path)
    end
    nil
  end

  def installed_ruby(pattern, executable)
    roots = []
    roots << ENV["RBENV_ROOT"] if ENV["RBENV_ROOT"]
    roots << File.join(Dir.home, ".rbenv")
    roots << File.join(Dir.home, ".asdf")
    roots.uniq.each do |root|
      paths = Dir[File.join(root, "installs", "ruby", pattern, "bin",
                            executable)]
      paths += Dir[File.join(root, "versions", pattern, "bin", executable)]
      path = paths.sort.last
      return path if path && File.executable?(path)
    end
    nil
  end

  def usable_engine(path)
    return nil unless path && File.executable?(path)

    _output, ok = capture(path, "-e", "", chdir: ROOT)
    ok ? path : nil
  end

  def optional_engines
    return @optional_engines if defined?(@optional_engines)

    truffle = ENV["TRUFFLERUBY_BIN"]
    if !truffle && ENV["GRAALVM_HOME"]
      truffle = File.join(ENV["GRAALVM_HOME"], "bin", "ruby")
    end
    truffle = usable_engine(truffle)
    truffle ||= find_command("truffleruby")
    truffle = usable_engine(truffle)
    truffle ||= installed_ruby("truffleruby*", "ruby")
    truffle = usable_engine(truffle)

    jruby = ENV["JRUBY_BIN"]
    jruby ||= File.join(ENV["JRUBY_HOME"], "bin", "jruby") if ENV["JRUBY_HOME"]
    jruby = usable_engine(jruby)
    jruby ||= find_command("jruby")
    jruby = usable_engine(jruby)
    jruby ||= installed_ruby("jruby*", "jruby")
    jruby = usable_engine(jruby)

    @optional_engines = {
      "truffleruby" => truffle,
      "jruby" => jruby
    }.compact
  end

  def optional_engine_args
    optional_engines.flat_map do |name, path|
      ["--engine", "#{name}=#{path}"]
    end
  end

  def engine_paths(args)
    paths = {
      "cruby" => File.join(TOP, "build", "ruby"),
      "cruby+yjit" => File.join(TOP, "build", "ruby"),
      "cruby+zjit" => File.join(TOP, "build", "ruby"),
      "rpyyarv" => File.join(ROOT, "rpyyarv"),
      "rpyyarv-jit" => File.join(ROOT, "rpyyarv-jit")
    }.merge(optional_engines)
    args.each_with_index do |arg, index|
      spec = if arg.start_with?("--engine=")
               arg.delete_prefix("--engine=")
             elsif arg == "--engine"
               args[index + 1]
             end
      next unless spec

      name, path = spec.split("=", 2)
      paths[name] = File.expand_path(path) if name && path
    end
    paths
  end

  def binary_metadata(paths)
    paths.transform_values do |path|
      next { "path" => path, "missing" => true } unless File.file?(path)

      stat = File.stat(path)
      { "path" => path, "bytes" => stat.size,
        "mtime" => stat.mtime.utc.iso8601,
        "sha256" => Digest::SHA256.file(path).hexdigest }
    end
  end

  def performance(args, results_root)
    run = Run.new("performance", results_root)
    raw = File.join(run.dir, "raw.json")
    argv = [driver_ruby, File.join(ROOT, "scripts", "bench.rb"),
            "--raw", raw] + optional_engine_args + args
    run.manifest["optional_engines"] = optional_engines
    run.manifest["engine_binaries"] = binary_metadata(engine_paths(args))
    ok = run.execute("performance", base_env, argv)
    if File.exist?(raw)
      begin
        Analyzer.analyze(raw, run.dir)
        Plotter.plot(raw, run.dir)
      rescue StandardError => error
        run.manifest["postprocess_error"] =
          "#{error.class}: #{error.message}"
        warn "postprocessing failed: #{error.message}"
        ok = false
      end
    end
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def boundary(args, results_root)
    run = Run.new("boundary", results_root)
    argv = [driver_ruby, File.join(ROOT, "scripts", "bench.rb"),
            "--foreign=20"] + args
    ok = run.execute("boundary", base_env, argv)
    log = File.join(run.dir, "boundary.log")
    count = Boundary.extract(log, File.join(run.dir, "boundary.csv"))
    run.manifest["boundary_rows"] = count
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def coverage(args, results_root)
    run = Run.new("coverage", results_root)
    bench = [driver_ruby, File.join(ROOT, "scripts", "bench.rb")]
    ok = run.execute("inventory", base_env, bench + ["--inventory"] + args)
    ok &= run.execute("foreign", base_env, bench + ["--foreign=20"] + args)
    inventory = begin
      JSON.parse(File.read(File.join(ROOT, ".bench-inventory.json")))
    rescue StandardError
      {}
    end
    rows = Boundary.coverage(File.join(run.dir, "foreign.log"), inventory,
                             File.join(run.dir, "coverage.csv"))
    run.manifest["coverage_rows"] = rows.size
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  # Item 8: one binary, RPYYARV_NO_REQUIRE forced off and left to the probe.
  def delegation(args, results_root)
    run = Run.new("delegation", results_root)
    bench = [driver_ruby, File.join(ROOT, "scripts", "bench.rb")]
    raws = {}
    ok = %w[gem-require no-gem-require].all? do |mode|
      raw = File.join(run.dir, "#{mode}.json")
      raws[mode] = raw
      run.execute(mode, base_env,
                  bench + ["--raw", raw, "--#{mode}", "--no-jsonl"] + args)
    end
    write_delegation(raws, File.join(run.dir, "delegation.csv"))
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def write_delegation(raws, csv_path)
    medians = raws.transform_values do |path|
      next {} unless File.exist?(path)

      JSON.parse(File.read(path)).to_h { |key, value| [key, value["median"]] }
    end
    keys = medians.values.flat_map(&:keys).uniq.sort
    rows = keys.filter_map do |key|
      suite, benchmark, engine = key.split("/", 3)
      native = medians["gem-require"][key]
      delegated = medians["no-gem-require"][key]
      next unless native && delegated&.positive?

      { "suite" => suite, "benchmark" => benchmark, "engine" => engine,
        "native_ms" => native, "delegated_ms" => delegated,
        "native_penalty" => native / delegated - 1.0 }
    end
    Csv.write(csv_path, %w[suite benchmark engine native_ms delegated_ms
                           native_penalty], rows)
  end

  # Item 5: crash rate versus nursery size, the hexapdf dose-response.
  def nursery(args, results_root)
    trials = Integer(ENV.fetch("EVAL_TRIALS", "5"))
    script = args.shift or abort "usage: nursery SCRIPT [SIZE ...]"
    sizes = args.empty? ? EvaluationConfig::GC_NURSERIES : args.map { |v| Integer(v) }
    run = Run.new("nursery", results_root)
    rows = sizes.map do |size|
      failures = (1..trials).count do |trial|
        env = base_env.merge("PYPY_GC_NURSERY" => size.to_s)
        !run.execute("nursery-#{size}-#{trial}", env,
                     [File.join(ROOT, "rpyyarv-jit"), script])
      end
      { "nursery_bytes" => size, "trials" => trials, "failures" => failures,
        "failure_rate" => failures.to_f / trials }
    end
    Csv.write(File.join(run.dir, "nursery.csv"),
              %w[nursery_bytes trials failures failure_rate], rows)
    run.finish(true)
    puts "artifacts: #{run.dir}"
    0
  end

  # Item 6: runtime ablations only; build variants are reported, not run.
  def ablate(args, results_root)
    names = args.take_while { |arg| EvaluationConfig::ABLATIONS.key?(arg) }
    names = EvaluationConfig::ABLATIONS.keys if names.empty?
    rest = args.drop(names.size)
    run = Run.new("ablation", results_root)
    run.manifest["build_ablations"] = EvaluationConfig::BUILD_ABLATIONS
    rows = names.map do |name|
      raw = File.join(run.dir, "#{name}.json")
      argv = [driver_ruby, File.join(ROOT, "scripts", "bench.rb"),
              "--raw", raw, "--no-jsonl"] + rest
      ok = run.execute(name, base_env.merge(EvaluationConfig::ABLATIONS[name]),
                       argv)
      { "ablation" => name,
        "env" => EvaluationConfig::ABLATIONS[name].map { |k, v| "#{k}=#{v}" }.join(" "),
        "status" => ok ? "ok" : "FAIL", "raw" => File.basename(raw) }
    end
    Csv.write(File.join(run.dir, "ablation.csv"),
              %w[ablation env status raw], rows)
    run.finish(rows.all? { |row| row["status"] == "ok" })
    puts "artifacts: #{run.dir}"
    puts "build-only ablations (need a translation, not run here):"
    EvaluationConfig::BUILD_ABLATIONS.each { |k, v| puts format("  %-16s %s", k, v) }
    0
  end

  def child_script(kind, script, args, results_root)
    run = Run.new(kind, results_root)
    raw = File.join(run.dir, "#{kind}.json")
    argv = [driver_ruby, File.join(__dir__, script), "--raw", raw] + args
    ok = run.execute(kind, base_env, argv)
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
    probe = ENV.fetch("EVAL_GC_SCRIPT", File.join(ROOT, "test", "fastops.rb"))
    run = Run.new("gc", results_root)
    rows = limits.map do |limit|
      argv = ["make", "gccheck", "GCLIMIT=#{limit}"]
      ok = run.execute("gc-#{limit}", base_env, argv, chdir: ROOT)
      gccheck_row(limit, File.join(run.dir, "gc-#{limit}.log"))
        .merge("passed" => ok)
        .merge(mark_overhead(limit, probe))
    end
    ok = rows.all? { |row| row["passed"] }
    Csv.write(File.join(run.dir, "gc.csv"),
              %w[malloc_limit ok skipped failed passed root_mark_walks
                 root_mark_ns rpython_heap_bytes], rows)
    run.manifest["gc_limits"] = limits
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def gccheck_row(limit, log_path)
    tail = File.exist?(log_path) ? File.read(log_path) : ""
    match = tail.match(/gccheck: (\d+) ok, (\d+) skipped, (\d+) failed/)
    { "malloc_limit" => limit, "ok" => match && match[1].to_i,
      "skipped" => match && match[2].to_i, "failed" => match && match[3].to_i }
  end

  # A separate probe run: the coverage report is never a timed measurement.
  def mark_overhead(limit, script)
    env = base_env.merge("RPYYARV_COVERAGE" => "1",
                         "RUBY_GC_MALLOC_LIMIT" => limit.to_s)
    out, = Open3.capture2e(env, File.join(ROOT, "rpyyarv-jit"), script,
                           chdir: ROOT)
    { "root_mark_walks" => out[/root marking: (\d+) walk/, 1]&.to_i,
      "root_mark_ns" => out[/root marking: \d+ walk\(s\), (\d+) ns/, 1]&.to_i,
      "rpython_heap_bytes" => out[/heap footprint: rpython (\d+)/, 1]&.to_i }
  rescue StandardError
    {}
  end

  def mechanisms(args, results_root)
    run = Run.new("mechanisms", results_root)
    raw = File.join(run.dir, "mechanisms.json")
    argv = [driver_ruby, File.join(__dir__, "mechanisms.rb"),
            "--raw", raw] + args
    ok = run.execute("mechanisms", base_env, argv)
    if File.exist?(raw)
      begin
        Plotter.plot_mechanisms(raw, run.dir)
      rescue StandardError => error
        run.manifest["postprocess_error"] =
          "#{error.class}: #{error.message}"
        warn "mechanism plotting failed: #{error.message}"
        ok = false
      end
    end
    run.finish(ok)
    puts "artifacts: #{run.dir}"
    ok ? 0 : 1
  end

  def doctor
    rows = {
      "repository" => [TOP, :directory],
      "ruby" => [driver_ruby, :executable],
      "bench driver" => [File.join(ROOT, "scripts", "bench.rb"), :file],
      "AWFY suite" => [File.join(ROOT, "awfy", "benchmarks", "Ruby"),
                       :directory],
      "ruby-bench suite" => [File.join(ROOT, "ruby-bench", "benchmarks"),
                             :directory],
      "cruby" => [File.join(build_dir, "ruby"), :engine],
      "rpyyarv" => [File.join(ROOT, "rpyyarv"), :engine],
      "rpyyarv-jit" => [File.join(ROOT, "rpyyarv-jit"), :engine],
      "truffleruby (optional)" => [optional_engines["truffleruby"],
                                   :engine],
      "jruby (optional)" => [optional_engines["jruby"], :engine],
      "rebench (optional)" => [
        ENV.fetch("PATH", "").split(File::PATH_SEPARATOR)
           .map { |dir| File.join(dir, "rebench") }
           .find { |path| File.executable?(path) },
        :executable
      ]
    }
    states = rows.to_h do |name, (path, kind)|
      state = doctor_state(path, kind)
      puts format("%-20s %-7s %s", name, state, path || "-")
      [name, state]
    end
    required = states.reject { |name, _state| name.include?("optional") }
    required.values.all? { |state| state == "ok" } ? 0 : 1
  end

  def doctor_state(path, kind)
    return "missing" unless path

    present = case kind
              when :directory then File.directory?(path)
              when :file then File.file?(path)
              else File.executable?(path)
              end
    return "missing" unless present
    return "ok" unless kind == :engine

    _output, ok = capture(base_env, path, "-e", "")
    ok ? "ok" : "broken"
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
        boundary [BENCH-ARGS]    run the non-timing delegation check
        coverage [BENCH-ARGS]    native/delegated compatibility and boundary calls
        crossing [ARGS]          nanoseconds per boundary send versus CRuby
        delegation [BENCH-ARGS]  native versus delegated gems, same binary
        memory [MECH-ARGS]       peak RSS per engine and benchmark
        mechanisms [MECH-ARGS]  collect tracing, boundary, YJIT, and ZJIT stats
        gc [LIMIT ...]           run gccheck at each malloc limit
        nursery SCRIPT [SIZE...] crash rate versus PYPY_GC_NURSERY
        ablate [NAME ...] [ARGS] runtime ablations; lists the build-only ones
        analyze RAW [OUT-DIR]    convert bench.rb JSON to tidy CSV
        plot RAW [OUT-DIR]       render ratio and log-log scatter SVGs
        report DIR [OUT.org]     turn a results directory's CSVs into org tables
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
    when "coverage" then coverage(argv, results_root)
    when "crossing" then child_script("crossing", "crossing.rb", argv, results_root)
    when "memory" then child_script("memory", "memory.rb", argv, results_root)
    when "delegation" then delegation(argv, results_root)
    when "nursery" then nursery(argv, results_root)
    when "ablate" then ablate(argv, results_root)
    when "mechanisms" then mechanisms(argv, results_root)
    when "gc" then gc_sweep(argv, results_root)
    when "report"
      dir = argv.shift or abort usage
      puts Org.write(dir, argv.shift || File.join(dir, "tables.org"))
      0
    when "analyze"
      raw = argv.shift or abort usage
      out = argv.shift || File.dirname(File.expand_path(raw))
      puts JSON.pretty_generate(Analyzer.analyze(raw, out))
      0
    when "plot"
      raw = argv.shift or abort usage
      out = argv.shift || File.dirname(File.expand_path(raw))
      puts Plotter.plot(raw, out)
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
