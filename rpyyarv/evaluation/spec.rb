#!/usr/bin/env ruby
# frozen_string_literal: true

# Run ruby/spec one file per process under each engine and tally examples.
# A file is the unit because a crash or hang under rpyyarv must not take
# the rest of the suite with it, and because rpyyarv delegates whole files
# to CRuby when an iseq is unsupported; RPYYARV_DEBUG=load reports that.
#
#   ruby evaluation/spec.rb --suite language --suite core [--engine NAME=PATH]
#
# Writes <results>/spec.csv (one row per file and engine) and spec-summary.csv
# (one row per suite directory and engine).

require "fileutils"
require "json"
require "open3"
require "optparse"
require "timeout"

module SpecEval
  HERE = File.dirname(File.expand_path(__FILE__))
  ROOT = File.expand_path("..", HERE)
  TOP = File.expand_path("..", ROOT)
  BUILD = File.join(TOP, "build")
  SPEC = File.join(TOP, "spec", "ruby")
  MSPEC = File.join(TOP, "spec", "mspec", "bin", "mspec")

  ENGINES = {
    "cruby" => File.join(BUILD, "ruby"),
    "rpyyarv" => File.join(ROOT, "rpyyarv"),
    "rpyyarv-jit" => File.join(ROOT, "rpyyarv-jit"),
  }.freeze

  SUITES = {
    "language" => "language",
    "core" => "core",
    "library" => "library",
    "capi" => "optional/capi",
    "command_line" => "command_line",
  }.freeze

  module_function

  def csv_line(fields)
    fields.map { |f| f.to_s =~ /[,"\n]/ ? "\"#{f.to_s.gsub('"', '""')}\"" : f.to_s }
          .join(",")
  end

  def env
    arch = File.basename(File.dirname(File.dirname(
      Dir.glob(File.join(BUILD, ".ext", "include", "*", "ruby", "config.h")).first.to_s)))
    lib = [File.join(TOP, "lib"), File.join(BUILD, ".ext", "common"), BUILD,
           File.join(BUILD, ".ext", arch.to_s)].join(":")
    {
      "RPYYARV_BUILD" => BUILD,
      "RUBYLIB" => lib,
      "DYLD_LIBRARY_PATH" => BUILD,
      "LD_LIBRARY_PATH" => BUILD,
      "RPYYARV_DEBUG" => "load",
    }
  end

  def run_file(engine_path, file, timeout)
    # No mspec --timeout: its TimeoutAction needs a Thread, which rpyyarv
    # refuses; the whole process is killed from outside instead.
    cmd = [File.join(BUILD, "ruby"), MSPEC, "run", "-t", engine_path,
           "-f", "yaml"]
    # The C-API specs compile an extension with mkmf against the uninstalled
    # build; CRuby's own fake rbconfig points mkmf at it. rpyyarv boots with
    # --disable-gems, so rbconfig must be loaded before the fake's hooks.
    if file.include?("/optional/capi/")
      fake = Dir.glob(File.join(BUILD, "*-fake.rb")).first
      cmd += ["-T", "-rrbconfig", "-T", "-r#{fake}"] if fake
    end
    cmd << file
    out = err = ""
    status = nil
    began = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    begin
      Open3.popen3(env, *cmd, chdir: SPEC) do |i, o, e, t|
        i.close
        Timeout.timeout(timeout) do
          out = o.read
          err = e.read
          status = t.value
        end
      rescue Timeout::Error
        Process.kill("KILL", t.pid) rescue nil
        status = :timeout
      end
    end
    elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - began
    parse(out, err, status, elapsed).merge(stdout: out, stderr: err)
  end

  def parse(out, err, status, elapsed)
    row = { examples: nil, expectations: nil, failures: nil, errors: nil,
            tagged: nil, files_native: nil, files_delegated: nil,
            delegated: nil, exit: nil, outcome: nil, seconds: elapsed.round(2) }
    %w[examples expectations failures errors tagged].each do |k|
      row[k.to_sym] = Regexp.last_match(1).to_i if out =~ /^#{k}: (\d+)/
    end
    # RPYYARV_DEBUG=load prints one line per file the require path finished:
    # "done" ran on rpyyarv, "cruby" was handed to the host as a whole.
    loads = err.scan(/^\[rpyyarv\] load #\d+ (done|cruby) (\S+)/)
    unless loads.empty?
      row[:files_native] = loads.count { |k, _| k == "done" }
      delegated = loads.select { |k, _| k == "cruby" }.map { |_, f| f }
      row[:files_delegated] = delegated.size
      specs = delegated.select { |f| f.end_with?("_spec.rb") }
      row[:delegated] = specs.map { |f| File.basename(f) }.join(";") unless specs.empty?
    end
    row[:exit] =
      if status == :timeout then "timeout"
      elsif status.signaled? then "SIG#{Signal.signame(status.termsig)}"
      else status.exitstatus.to_s
      end
    row[:outcome] =
      if status == :timeout then "hang"
      elsif status.signaled? then "crash"
      elsif row[:examples].nil? then "error"
      elsif (row[:failures] || 0).zero? && (row[:errors] || 0).zero? then "pass"
      else "fail"
      end
    row
  end

  def spec_files(suite)
    Dir.glob(File.join(SPEC, SUITES.fetch(suite), "**", "*_spec.rb")).sort
  end

  def main(argv)
    opts = { suites: [], engines: {}, timeout: 60, jobs: 1, out: nil,
             filter: nil }
    OptionParser.new do |o|
      o.on("--suite NAME") { |s| opts[:suites] << s }
      o.on("--engine NAME=PATH") { |s| n, p = s.split("=", 2); opts[:engines][n] = p }
      o.on("--timeout SEC", Integer) { |t| opts[:timeout] = t }
      o.on("--jobs N", Integer) { |j| opts[:jobs] = j }
      o.on("--out DIR") { |d| opts[:out] = d }
      o.on("--filter RE") { |re| opts[:filter] = Regexp.new(re) }
    end.parse!(argv)
    opts[:suites] = %w[language core] if opts[:suites].empty?
    engines = opts[:engines].empty? ? ENGINES.reject { |k, _| k == "rpyyarv" } : opts[:engines]
    out = opts[:out] || File.join(HERE, "results",
                                  "#{Time.now.utc.strftime('%Y%m%dT%H%M%SZ')}-spec-#{Process.pid}")
    FileUtils.mkdir_p(out)
    manifest = { started: Time.now.utc.iso8601, engines: engines, suites: opts[:suites],
                 timeout: opts[:timeout],
                 commit: `git -C #{TOP} rev-parse HEAD`.strip,
                 ruby: `#{env.map { |k, v| "#{k}=#{v}" }.join(' ')} #{ENGINES['cruby']} -v`.strip }
    File.write(File.join(out, "manifest.json"), JSON.pretty_generate(manifest))

    rows = []
    csv_path = File.join(out, "spec.csv")
    header = %w[suite file engine outcome exit examples expectations failures
                errors tagged files_native files_delegated delegated seconds]
    File.open(csv_path, "w") do |csv|
      csv.puts csv_line(header)
      opts[:suites].each do |suite|
        files = spec_files(suite)
        files.select! { |f| opts[:filter] =~ f } if opts[:filter]
        queue = files.product(engines.to_a)
        mutex = Mutex.new
        workers = Array.new(opts[:jobs]) do
          Thread.new do
            loop do
              item = mutex.synchronize { queue.shift }
              break unless item

              file, (ename, epath) = item
              rel = file.sub("#{SPEC}/", "")
              r = run_file(epath, file, opts[:timeout])
              if r[:outcome] != "pass"
                log = File.join(out, "logs", ename, rel.sub(/\.rb\z/, ".log"))
                FileUtils.mkdir_p(File.dirname(log))
                File.write(log, "#{r[:stdout]}\n--- stderr ---\n#{r[:stderr]}")
              end
              row = [suite, rel, ename, r[:outcome], r[:exit], r[:examples],
                     r[:expectations], r[:failures], r[:errors], r[:tagged],
                     r[:files_native], r[:files_delegated], r[:delegated],
                     r[:seconds]]
              mutex.synchronize do
                csv.puts csv_line(row)
                csv.flush
                rows << header.zip(row).to_h
                warn format("%-8s %-12s %-50s ex=%s fail=%s err=%s %s", suite,
                            ename, rel[0, 50], r[:examples], r[:failures],
                            r[:errors], r[:outcome] == "pass" ? "" : r[:outcome])
              end
            end
          end
        end
        workers.each(&:join)
      end
    end
    summarise(rows, File.join(out, "spec-summary.csv"))
    manifest[:finished] = Time.now.utc.iso8601
    File.write(File.join(out, "manifest.json"), JSON.pretty_generate(manifest))
    warn "wrote #{out}"
  end

  # One row per (suite directory, engine): files by outcome and example tallies.
  # A file that crashed or hung contributes its CRuby example count to the
  # "lost" column so the pass rate is over the same denominator for every engine.
  def summarise(rows, path)
    by_dir = Hash.new { |h, k| h[k] = [] }
    rows.each do |r|
      dir = r["file"].split("/")[0, r["suite"] == "core" ? 2 : 1].join("/")
      by_dir[[r["suite"], dir, r["engine"]]] << r
    end
    cruby_examples = rows.select { |r| r["engine"] == "cruby" }
                         .to_h { |r| [r["file"], r["examples"].to_i] }
    File.open(path, "w") do |csv|
      csv.puts csv_line(%w[suite dir engine files pass fail crash hang error
                           delegated examples failures errors lost_examples
                           pass_rate])
      by_dir.keys.sort.each do |key|
        rs = by_dir[key]
        outcomes = rs.group_by { |r| r["outcome"] }.transform_values(&:size)
        ex = rs.sum { |r| r["examples"].to_i }
        fl = rs.sum { |r| r["failures"].to_i }
        er = rs.sum { |r| r["errors"].to_i }
        lost = rs.select { |r| r["examples"].nil? || r["examples"].to_s.empty? }
                 .sum { |r| cruby_examples[r["file"]] || 0 }
        delegated = rs.sum { |r| r["files_delegated"].to_i }
        denom = ex + lost
        rate = denom.zero? ? nil : ((ex - fl - er).to_f / denom).round(4)
        csv.puts csv_line([*key, rs.size, outcomes["pass"] || 0, outcomes["fail"] || 0,
                outcomes["crash"] || 0, outcomes["hang"] || 0,
                outcomes["error"] || 0, delegated, ex, fl, er, lost, rate])
      end
    end
  end
end

SpecEval.main(ARGV) if $PROGRAM_NAME == __FILE__
