# frozen_string_literal: true

require "open3"
require "tmpdir"

# Host collections each gccheck script actually gets per malloc limit and
# engine, read from GC.stat at exit; rpyyarv's root walks need its coverage
# report, so both rpyyarv engines run with RPYYARV_COVERAGE=1 here.
module GcFreq
  FIELDS = %w[gc_count major_gc_count minor_gc_count gc_time_ms
              malloc_limit_at_exit].freeze

  module_function

  def scripts(root)
    out, status = Open3.capture2("make", "-s", "gcscripts", chdir: root)
    status.success? ? out.split : []
  end

  def engines(root, build)
    { "cruby" => [File.join(build, "ruby"), "--disable-gems"],
      "rpyyarv" => [File.join(root, "rpyyarv")],
      "rpyyarv-jit" => [File.join(root, "rpyyarv-jit")] }
  end

  # limit nil is the host default, the baseline every multiplier divides by.
  def collect(root, build, env, limits, timeout: 60)
    prelude = File.join(__dir__, "gcstat_prelude.rb")
    Dir.mktmpdir("gcfreq") do |tmp|
      out_path = File.join(tmp, "stat")
      scripts(root).product([nil] + limits, engines(root, build).to_a)
                   .map do |script, limit, (engine, argv)|
        File.delete(out_path) if File.exist?(out_path)
        run_env = env.merge("RUBYOPT" => "-r#{prelude}",
                            "RPYYARV_GCSTAT_OUT" => out_path)
        run_env["RUBY_GC_MALLOC_LIMIT"] = limit.to_s if limit
        run_env["RPYYARV_COVERAGE"] = "1" unless engine == "cruby"
        _out, err, status = Open3.capture3(
          run_env, "perl", "-e", "alarm shift; exec @ARGV", timeout.to_s,
          *argv, script, chdir: root
        )
        stat = File.exist?(out_path) ? File.read(out_path).split : []
        walks = err.scrub.match(/root marking: (\d+) walk\(s\), (\d+) ns/)
        { "script" => script.delete_prefix("#{root}/"),
          "malloc_limit" => limit || "default", "engine" => engine,
          "exit" => status.exitstatus || "signal #{status.termsig}",
          "root_walks" => walks && walks[1].to_i,
          "root_walk_ns" => walks && walks[2].to_i
        }.merge(FIELDS.zip(stat.map(&:to_i)).to_h)
      end
    end
  end

  # Per limit and engine: the collection-count multiplier over the default.
  def summarize(rows)
    base = rows.select { |r| r["malloc_limit"] == "default" }
               .to_h { |r| [[r["script"], r["engine"]], r["gc_count"]] }
    stats = RPyYARVEvaluation::Analyzer
    groups = rows.group_by { |r| [r["malloc_limit"], r["engine"]] }
    groups.map do |(lim, eng), g|
      known = g.select { |r| r["gc_count"] && base[[r["script"], eng]] }
      ratios = known.filter_map do |r|
        b = base[[r["script"], eng]]
        r["gc_count"].to_f / b if b.positive? && r["gc_count"].positive?
      end
      walks = g.filter_map { |r| r["root_walks"] }
      { "malloc_limit" => lim, "engine" => eng, "scripts" => g.size,
        "with_stat" => g.count { |r| r["gc_count"] },
        "n_base_zero" => known.count { |r| base[[r["script"], eng]].zero? },
        "n_ratio" => ratios.size,
        "count_multiplier_geomean" => stats.geomean(ratios),
        "count_multiplier_min" => ratios.min,
        "count_multiplier_max" => ratios.max,
        "median_gc_count" => stats.median_value(g.map { |r| r["gc_count"] }),
        "median_root_walks" => stats.median_value(walks),
        "total_root_walk_ns" => g.sum { |r| r["root_walk_ns"].to_i } }
    end
  end
end
