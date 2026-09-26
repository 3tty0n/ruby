#!/usr/bin/env ruby
# frozen_string_literal: true

# The price of immobilise-on-retain: per benchmark and engine, the objects
# a compacting collection had to leave in place, and how densely the heap
# packs afterwards.  One process per (benchmark, engine), after the
# benchmark's own iterations, via evaluation/immobile_prelude.rb.
#
#   ruby evaluation/immobile.rb --out DIR [--suite awfy|ruby-bench|all]
#                                [--filter NAME ...]

require "fileutils"
require "json"
require "open3"
require "optparse"

module Immobile
  HERE = File.dirname(File.expand_path(__FILE__))
  ROOT = File.expand_path("..", HERE)
  PRELUDE = File.join(HERE, "immobile_prelude.rb")
  FIELDS = %w[suite benchmark engine status pinned pinned_bytes live slots
              pages_before pages moved types].freeze

  module_function

  def load_bench
    load File.join(ROOT, "scripts", "bench.rb") unless defined?(AwfySuite)
  end

  def measure(argv, script, env, timeout)
    full = timeout_argv(timeout, ["nice", "-n", "19"] + argv +
                        ["-r", PRELUDE, script])
    # objspace is a built extension: the uninstalled build needs its path.
    env = env.merge("RUBYLIB" => [uninstalled_rubylib, env["RUBYLIB"]]
                                   .compact.join(File::PATH_SEPARATOR))
    _out, err, status = Open3.capture3(env, *full)
    line = err[/^IMMOBILE .*$/]
    return { "status" => "FAIL" } unless status.success? && line

    line.scan(/(\w+)=(\S+)/).to_h.merge("status" => "ok")
  end

  def main(argv)
    load_bench
    opts = { suite: "all", filters: [], out: nil }
    OptionParser.new do |o|
      o.on("--suite NAME") { |v| opts[:suite] = v }
      o.on("--filter NAME") { |v| opts[:filters] << v }
      o.on("--out DIR") { |v| opts[:out] = v }
    end.parse!(argv)
    abort "--out is required" unless opts[:out]
    FileUtils.mkdir_p(opts[:out])
    engines = BASE_ENGINES.select { |n, _| %w[cruby rpyyarv-jit].include?(n) }
    suites = { "all" => %w[awfy ruby-bench], "awfy" => %w[awfy],
               "ruby-bench" => %w[ruby-bench] }.fetch(opts[:suite])
    env = base_env
    csv = File.open(File.join(opts[:out], "immobile.csv"), "w")
    csv.puts FIELDS.join(",")
    suites.each do |name|
      suite = name == "awfy" ? AwfySuite.new(opts) : RubyBenchSuite.new(opts)
      next unless suite.available?

      suite.benchmarks.each do |bench|
        next unless opts[:filters].empty? ||
                    opts[:filters].any? { |f| bench.include?(f) }

        engines.each do |ename, eargv|
          row = { "suite" => suite.name, "benchmark" => bench,
                  "engine" => ename }
          suite.with_script(bench) do |script, senv, _|
            row.merge!(measure(eargv, script, env.merge(senv || {}),
                               suite.timeout))
          end
          csv.puts FIELDS.map { |k| row[k] }.join(",")
          csv.flush
          warn "#{bench} #{ename} #{row['status']} pinned=#{row['pinned']}"
        end
      end
    end
    csv.close
  end
end

Immobile.main(ARGV) if $PROGRAM_NAME == __FILE__
