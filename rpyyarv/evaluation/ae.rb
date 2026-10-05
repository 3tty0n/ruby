#!/usr/bin/env ruby
# frozen_string_literal: true

# Artifact evaluation: the benchmark subsets of ae-smoke and ae-quick, and a
# checker that compares a run with the paper's numbers (ae-paper.json).
#   ae.rb filters|delegation|gcscripts LEVEL   flags for campaign.sh
#   ae.rb check LEVEL DIR ...    DIR: a campaign log dir or a results dir

require "json"
require "tmpdir"
require_relative "run"
require_relative "correlations"

module AE
  AWFY = %w[bounce cd deltablue havlak json list mandelbrot nbody permute
            queens richards sieve storage towers].freeze
  # ruby-bench by benchmarks.yml category, spread over each category's
  # jit/yjit range. The AWFY filters json and nbody also select
  # json_parse_float, json_parse_string, ruby-json and ruby-bench's nbody.
  RUBY_BENCH = {
    "headline" => %w[chunky-png liquid-render railsbench hexapdf shipit
                     lobsters rubocop],
    "other" => %w[nqueens fannkuchredux graphql-native binarytrees],
    "micro" => %w[keyword_args 30k_methods send_cfunc_block 30k_ifelse throw
                  setivar_young object-new-initialize fib structaref],
    "gc" => %w[gcbench]
  }.freeze
  FILTERS = {
    "smoke" => %w[richards deltablue keyword_args 30k_methods railsbench],
    "quick" => AWFY + RUBY_BENCH.values.flatten
  }.freeze
  # campaign.sh's delegation benchmarks that are in the quick subset.
  DELEGATION = %w[railsbench shipit lobsters hexapdf rubocop].freeze
  # ae-smoke's gccheck and compaction subset: GC, fibers, threads, moves.
  GCSCRIPTS = %w[test/compaction.rb test/fibercycle.rb test/fiberblock.rb
                 test/threads.rb test/threadmark.rb test/singletongc.rb
                 test/purgegc.rb test/procdup.rb test/exceptions.rb
                 test/kwargs.rb test/bighash.rb test/strops.rb
                 test/enumerators.rb test/redefcache.rb].freeze
  # The one crash the paper reports under a stress (fixed after 1313bdb9d6).
  KNOWN_CRASHES = [%w[c-timer-compact shipit rpyyarv-jit]].freeze
  HEADLINE = %w[keyword_args 30k_methods railsbench lobsters shipit rubocop
                hexapdf].freeze
  PAPER = File.join(__dir__, "ae-paper.json")

  E = RPyYARVEvaluation
  A = E::Analyzer
  B = E::Bootstrap

  module_function

  def selected(names, level)
    return names if level == "full"

    names.select { |n| FILTERS.fetch(level).any? { |f| n.include?(f) } }
  end

  def flags(names) = names.flat_map { |n| ["--filter", n] }.join(" ")

  # [id, RQ, statement, rule, tolerance]
  CLAIMS = [
    ["steps_rc", "-", "campaign steps that exited non-zero", :zero],
    ["spec_language", "RQ1", "ruby/spec language pass rate, jit", :abs, 0.005],
    ["spec_core", "RQ1", "ruby/spec core pass rate, jit", :abs, 0.005],
    ["spec_capi", "RQ1", "ruby/spec C-API pass rate, jit", :abs, 0.005],
    ["corpus_failed", "RQ1", "benchmarks FAIL/DELEGATED under jit", :zero],
    ["native_iseq_pct", "RQ1", "median native iseq %", :abs, 5],
    ["boundary_share", "RQ1", "median CRuby share of sends", :abs, 0.01],
    ["gccheck_failed", "RQ2", "gccheck failures (all limits)", :zero],
    ["cycles_failed", "RQ2", "fibercycle.rb not ok under gccheck", :zero],
    ["compact_failed", "RQ2", "gccheck failures under (b)", :zero],
    ["nohook_fail_share", "RQ2", "share of benchmarks gc-no-hook breaks",
     :atleast, 0.5],
    ["gcfreq_jit", "RQ2", "GC count multiplier at 16384, jit", :abs, 0.2],
    ["gcfreq_cruby", "RQ2", "GC count multiplier at 16384, cruby", :abs,
     0.2],
    ["nursery_failures", "RQ2", "crashes over nursery sizes", :zero],
    ["stress_unexpected", "RQ2", "stress crashes beyond shipit/(c)/jit",
     :zero],
    ["stress_timeouts", "RQ2", "stress timeouts (rpyyarv engines)", :info],
    ["spec_stress_drift", "RQ2", "max language-rate drift, (a)(b)(d)",
     :abs, 0.002],
    ["jit_over_cruby", "RQ3", "geomean jit/cruby, CI below 1", :below],
    ["jit_over_yjit", "RQ3", "geomean jit/yjit", :overlap],
    ["jit_over_zjit", "RQ3", "geomean jit/zjit", :overlap],
    ["awfy_jit_over_yjit", "RQ3", "AWFY geomean jit/yjit", :overlap],
    ["interp_over_cruby", "RQ3", "geomean interp/cruby", :overlap],
    ["headline_side", "RQ3", "headline benchmarks on the paper's side of " \
                             "YJIT", :zero],
    ["faster_than_yjit", "RQ3", "share of benchmarks faster than YJIT",
     :abs, 0.15],
    ["delegation", "RQ3", "geomean native/delegated, jit, gem benchmarks",
     :rel, 0.25],
    ["crossing_factor", "RQ3", "worst crossing ratio vs paper (factor)",
     :atmost, 2],
    ["fast_paths_off", "RQ4", "fast-paths-off slowdown, jit", :overlap],
    ["fpo_keyword_args", "RQ4", "fast-paths-off on keyword_args", :atleast,
     50],
    ["method_inval", "RQ4", "method-invalidation-global, jit", :abs, 0.1],
    ["class_inval", "RQ4", "class-invalidation-global, jit", :abs, 0.1],
    ["const_inval", "RQ4", "constant-invalidation-global, jit", :abs, 0.1],
    ["jit_eager", "RQ4", "jit-params-eager, jit", :abs, 0.1],
    ["jit_lazy", "RQ4", "jit-params-lazy, jit", :abs, 0.1],
    ["corr_sends", "RQ4", "Pearson r, log1p sends vs log jit/yjit",
     :positive],
    ["corr_bridges", "RQ4", "Pearson r, log1p bridges/loop", :positive],
    ["compile_all", "RQ4", "median compile-time share", :atmost, 0.1],
    ["compile_awfy", "RQ4", "median compile-time share, AWFY", :atmost, 0.1],
    ["rss_over_cruby", "RQ5", "geomean peak RSS jit/cruby", :overlap],
    ["rss_over_yjit", "RQ5", "geomean peak RSS jit/yjit", :overlap],
    ["startup_jit_mb", "RQ5", "startup RSS MB, jit", :rel, 0.15],
    ["startup_cruby_mb", "RQ5", "startup RSS MB, cruby", :rel, 0.15],
    ["warmup_ratio", "RQ5", "median time-to-stable jit/yjit", :overlap]
  ].freeze

  # --- reading results -------------------------------------------------

  def read_csv(path)
    lines = File.readlines(path, chomp: true).reject(&:empty?)
    head = E::Org.split(lines[0])
    lines[1..].map { |l| head.zip(E::Org.split(l)).to_h }
  end

  def num(value) = value && Float(value, exception: false)

  # Campaign dirs expand to the results dirs their step logs name.
  def collect(paths)
    runs = Hash.new { |h, k| h[k] = [] }
    paths.each do |path|
      log = File.join(path, "campaign.log")
      unless File.exist?(log)
        add(runs, path)
        next
      end
      runs["campaign"] << path
      Dir[File.join(path, "step-*.log")].sort.each do |step|
        File.read(step).scrub.scan(/^artifacts: (\S+)$/) { add(runs, $1) }
      end
      File.read(log).scan(/ --out (\S+)/) { add(runs, $1) }
    end
    runs
  end

  def add(runs, dir)
    manifest = File.join(dir, "manifest.json")
    return unless File.exist?(manifest)

    kind = JSON.parse(File.read(manifest))["kind"]
    kind ||= "spec" if File.basename(dir).include?("-spec-")
    runs[kind] << dir if kind
  end

  def boot(rows, &stat)
    rng = Random.new(B::SEED)
    s = Array.new(B::RESAMPLES) do
      stat.call(Array.new(rows.size) { rows[rng.rand(rows.size)] })
    end.compact.sort
    [s[(0.025 * (s.size - 1)).round], s[(0.975 * (s.size - 1)).round]]
  end

  def gm(logs) = Math.exp(logs.sum / logs.size)

  # --- measured values, keyed by claim id ------------------------------

  def measure(runs, level)
    keep = ->(name) { !selected([name], level).empty? }
    m = {}
    campaign(runs["campaign"], m)
    performance(runs["performance"].last, keep, m)
    coverage(runs["coverage"].last, runs["boundary"].last, keep, m)
    crossing(runs["crossing"].last, m)
    delegation(runs["delegation"].last, keep, m)
    mechanisms(runs["mechanisms"].last, keep, m)
    memory(runs["memory"].last, keep, m)
    ablation(runs["ablation"], keep, m)
    gc(runs["gc"].last, m)
    nursery(runs["nursery"].last, m)
    stress(runs["stress"].last, keep, m)
    spec(runs["spec"], m)
    m
  end

  def campaign(dirs, m)
    return if dirs.empty?

    log = dirs.map { |d| File.read(File.join(d, "campaign.log")) }.join
    m["steps_rc"] = log.scan(/ END \S+ rc=(\d+)/).count { |(rc)| rc != "0" }
    { "gccheck_failed" => "ae-gccheck", "compact_failed" => "ae-compact" }
      .each do |id, name|
      path = dirs.map { |d| File.join(d, "step-#{name}.log") }
                 .find { |p| File.exist?(p) }
      tail = path && File.read(path).scrub[/gccheck: \d+ ok, \d+ \w+, (\d+)/, 1]
      m[id] = tail.to_i if tail
      m[id] = 1 if path && !tail
    end
  end

  def performance(dir, keep, m)
    return unless dir

    raw = JSON.parse(File.read(File.join(dir, "raw.json")))
    raw.select! { |k, _| keep[k.split("/")[1]] }
    Dir.mktmpdir("ae") do |tmp|
      path = File.join(tmp, "raw.json")
      File.write(path, JSON.generate(raw))
      A.analyze(path, tmp)
      summary = read_csv(File.join(tmp, "summary.csv"))
      all = summary.find { |r| r["suite"] == "all" }
      %w[cruby yjit zjit].each do |ref|
        m["jit_over_#{ref}"] = ci_of(all, "geomean_jit_over_#{ref}")
      end
      awfy = summary.find { |r| r["suite"] == "awfy" }
      m["awfy_jit_over_yjit"] = ci_of(awfy, "geomean_jit_over_yjit") if awfy
      m["corpus_failed"] = all["n_failed"].to_i + all["n_delegated"].to_i
      ratios = read_csv(File.join(tmp, "ratios.csv"))
      yjit = ratios.to_h do |r|
        [r["benchmark"], num(r["rpyyarv_jit_over_yjit"])]
      end
      known = yjit.values.compact
      m["faster_than_yjit"] = known.count { |v| v < 1 }.fdiv(known.size)
      m["headline_ratios"] = yjit.slice(*HEADLINE).compact
      warmup(File.join(tmp, "warmup-comparison.csv"), m)
    end
    interp(raw, m)
  end

  def ci_of(row, key)
    [num(row[key]), num(row["#{key}_lo"]), num(row["#{key}_hi"])]
  end

  def interp(raw, m)
    pairs = raw.keys.map { |k| k.split("/")[0, 2] }.uniq.filter_map do |s, b|
      t = raw["#{s}/#{b}/rpyyarv"]
      c = raw["#{s}/#{b}/cruby"]
      [t["per_proc"], c["per_proc"]] if t&.dig("median") && c&.dig("median")
    end
    return if pairs.empty?

    pt = gm(pairs.map { |t, c| Math.log(A.median_value(t)) -
                                Math.log(A.median_value(c)) })
    m["interp_over_cruby"] = [pt, *B.geomean_ci(pairs)]
  end

  def warmup(path, m)
    both = read_csv(path).filter_map { |r| num(r["time_to_stable_ratio"]) }
    return if both.empty?

    med = ->(rows) { A.median_value(rows) }
    m["warmup_ratio"] = [med.(both), *boot(both, &med)]
  end

  def coverage(dir, boundary, keep, m)
    if dir
      rows = read_csv(File.join(dir, "coverage.csv"))
             .select { |r| keep[r["benchmark"]] }
      pct = rows.select { |r| r["status"] == "NATIVE" }.filter_map do |r|
        a, b = r["iseqs"].to_s.split("/").map(&:to_f)
        100 * a / b if b&.positive?
      end
      m["native_iseq_pct"] = A.median_value(pct)
    end
    share = if boundary
              read_csv(File.join(boundary, "boundary.csv"))
                .select { |r| keep[r["benchmark"]] }
                .map { |r| r["cruby_share"] }
            elsif dir
              rows.map { |r| r["cruby_send_share"] }
            end
    return unless share

    m["boundary_share"] = A.median_value(share.filter_map { |v| num(v) })
  end

  def crossing(dir, m)
    return unless dir

    m["crossing"] = read_csv(File.join(dir, "crossing-overhead.csv"))
                    .reject { |r| r["kernel"].start_with?("native") }
                    .to_h { |r| [r["kernel"], num(r["ratio_vs_cruby"])] }
  end

  def delegation(dir, keep, m)
    return unless dir

    rows = read_csv(File.join(dir, "delegation.csv")).select do |r|
      r["engine"] == "rpyyarv-jit" && keep[r["benchmark"]]
    end
    m["delegation"] = A.geomean(rows.map do |r|
      num(r["native_ms"]) / num(r["delegated_ms"])
    end)
  end

  def mechanisms(dir, keep, m)
    return unless dir

    rows = JSON.parse(File.read(File.join(dir, "mechanisms.json")))
               .select { |r| keep[r["benchmark"]] }
    Correlations.analyze(rows).each do |r|
      next unless r["method"] == "pearson"

      id = r["predictor"].start_with?("cruby") ? "corr_sends" : "corr_bridges"
      m[id] = [r["r"], r["ci_lo"], r["ci_hi"]]
    end
    share = ->(g) { A.median_value(g.map { |r| r["compile_fraction"] }) }
    m["compile_all"] = share.(rows)
    m["compile_awfy"] = share.(rows.select { |r| r["suite"] == "awfy" })
  end

  def memory(dir, keep, m)
    return unless dir

    rows = read_csv(File.join(dir, "memory.csv"))
    peak = lambda do |g, e|
      num(g.find { |r| r["engine"] == e }&.[]("peak_rss_bytes"))
    end
    groups = rows.reject { |r| r["suite"] == "startup" }
                 .select { |r| keep[r["benchmark"]] }
                 .group_by { |r| [r["suite"], r["benchmark"]] }.values
    { "cruby" => "rss_over_cruby", "cruby+yjit" => "rss_over_yjit" }
      .each do |ref, id|
      logs = groups.filter_map do |g|
        j = peak[g, "rpyyarv-jit"]
        c = peak[g, ref]
        Math.log(j / c) if j && c
      end
      m[id] = [gm(logs), *boot(logs) { |s| gm(s) }] unless logs.empty?
    end
    start = rows.select { |r| r["suite"] == "startup" }
                .to_h { |r| [r["engine"], num(r["peak_rss_mb"])] }
    m["startup_jit_mb"] = start["rpyyarv-jit"]
    m["startup_cruby_mb"] = start["cruby"]
  end

  ABLATION_IDS = {
    "fast-paths-off" => "fast_paths_off",
    "method-invalidation-global" => "method_inval",
    "class-invalidation-global" => "class_inval",
    "constant-invalidation-global" => "const_inval",
    "jit-params-eager" => "jit_eager", "jit-params-lazy" => "jit_lazy"
  }.freeze

  def ablation(dirs, keep, m)
    raws = {}
    dirs.each do |d|
      Dir[File.join(d, "*.json")].each do |p|
        name = File.basename(p, ".json")
        raws[name] ||= JSON.parse(File.read(p)) unless name == "manifest"
      end
    end
    raws.transform_values! { |r| r.select { |k, _| keep[k.split("/")[1]] } }
    if (hook = raws["gc-no-hook"])
      broken = hook.select { |_, v| v["status"] }.keys
                   .map { |k| k.split("/")[0, 2] }.uniq
      total = hook.keys.map { |k| k.split("/")[0, 2] }.uniq
      m["nohook_fail_share"] = broken.size.fdiv(total.size)
    end
    base = raws["baseline"] or return
    ABLATION_IDS.each do |name, id|
      raw = raws[name] or next
      keys = base.keys.select do |k|
        k.end_with?("/rpyyarv-jit") && base[k]["per_proc"] &&
          raw[k]&.dig("per_proc")
      end
      next if keys.empty?

      pt = A.geomean(keys.map { |k| raw[k]["median"] / base[k]["median"] })
      m[id] = [pt, *B.geomean_ci(keys.map do |k|
        [raw[k]["per_proc"], base[k]["per_proc"]]
      end)]
      next unless name == "fast-paths-off"

      kw = keys.find { |k| k.include?("/keyword_args/") }
      m["fpo_keyword_args"] = raw[kw]["median"] / base[kw]["median"] if kw
    end
  end

  def gc(dir, m)
    return unless dir

    m["gccheck_failed"] = read_csv(File.join(dir, "gc.csv"))
                          .sum { |r| r["failed"].to_i }
    log = Dir[File.join(dir, "gc-*.log")].first
    m["cycles_failed"] =
      File.read(log).scrub.match?(/^ok\s+fibercycle\.rb$/) ? 0 : 1 if log
    path = File.join(dir, "gcfreq-summary.csv")
    return unless File.exist?(path)

    rows = read_csv(path).select { |r| r["malloc_limit"] == "16384" }
    pick = lambda do |e|
      num(rows.find { |r| r["engine"] == e }&.[]("count_multiplier_geomean"))
    end
    m["gcfreq_jit"] = pick["rpyyarv-jit"]
    m["gcfreq_cruby"] = pick["cruby"]
  end

  def nursery(dir, m)
    return unless dir

    m["nursery_failures"] = read_csv(File.join(dir, "nursery.csv"))
                            .sum { |r| r["failures"].to_i }
  end

  def stress(dir, keep, m)
    return unless dir

    # The paper's run was reclassified once; later runs classify themselves.
    path = %w[stress-reclassified.csv stress.csv].map { |f| File.join(dir, f) }
                                                 .find { |p| File.exist?(p) }
    rows = read_csv(path).select do |r|
      r["engine"] != "cruby" && r["stress"] != "none" && keep[r["benchmark"]]
    end
    crashes = rows.select { |r| r["outcome"] == "fail" }
                  .map { |r| r.values_at("stress", "benchmark", "engine") }
    m["stress_unexpected"] = (crashes - KNOWN_CRASHES).size
    m["stress_timeouts"] = rows.count { |r| r["outcome"] == "timeout" }
  end

  def spec(dirs, m)
    rates = dirs.to_h do |dir|
      [File.basename(dir)[/-spec-(.+)\z/, 1], spec_rates(dir)]
    end
    none = rates["none"] or return
    %w[language core capi].each { |s| m["spec_#{s}"] = none[s] }
    drift = rates.filter_map do |name, r|
      next unless name =~ /\A[abd]-/ && r["language"] && none["language"]

      (r["language"] - none["language"]).abs
    end
    m["spec_stress_drift"] = drift.max unless drift.empty?
  end

  # spec.rb's pass rate per suite, a crash or hang losing CRuby's examples.
  def spec_rates(dir)
    rows = read_csv(File.join(dir, "spec.csv"))
    cruby = rows.select { |r| r["engine"] == "cruby" }
                .to_h { |r| [r["file"], r["examples"].to_i] }
    rows.select { |r| r["engine"] == "rpyyarv-jit" }.group_by { |r| r["suite"] }
        .transform_values do |g|
      ex = g.sum { |r| r["examples"].to_i }
      bad = g.sum { |r| r["failures"].to_i + r["errors"].to_i }
      lost = g.select { |r| r["examples"].to_s.empty? }
              .sum { |r| cruby[r["file"]].to_i }
      (ex - bad).fdiv(ex + lost)
    end
  end

  # --- verdicts --------------------------------------------------------

  def derived(m, ref)
    if (h = m["headline_ratios"]) && (p = ref["headline_ratios"])
      m["headline_side"] = h.count { |b, v| p[b] && (v < 1) != (p[b] < 1) }
    end
    if (c = m["crossing"]) && (p = ref["crossing"])
      m["crossing_factor"] = c.filter_map do |k, v|
        [v / p[k], p[k] / v].max if v && p[k]
      end.max
    end
    m
  end

  def verdict(rule, value, ref, tol)
    return "SKIP" if value.nil? || (value.is_a?(Array) && value.include?(nil))
    absolute = %i[zero atleast atmost positive].include?(rule)
    return "INFO" if rule == :info || (ref.nil? && !absolute)

    pt = value.is_a?(Array) ? value[0] : value
    rp = ref.is_a?(Array) ? ref[0] : ref
    ok = case rule
         when :zero then value.zero?
         when :atleast then value >= tol
         when :atmost then value <= tol
         when :positive then value[1].positive?
         when :abs then (pt - rp).abs <= tol
         when :rel then (pt / rp - 1).abs <= tol
         when :overlap then value[1] <= ref[2] && ref[1] <= value[2]
         when :below
           value[2] < 1 && value[1] <= ref[2] && ref[1] <= value[2]
         end
    ok ? "PASS" : "WARN"
  end

  def show(value)
    case value
    when nil then "-"
    when Array then format("%s [%s, %s]", *value.map { |v| show(v) })
    when Float then format("%.4g", value)
    else value.to_s
    end
  end

  def check(level, paths)
    paper = JSON.parse(File.read(PAPER))
    ref = paper.fetch("full").merge(paper.fetch(level, {}))
    # Claims a level's subset is too small to decide are reported only.
    (ref.delete("info") || []).each { |id| ref[id] = nil }
    m = derived(measure(collect(paths), level), ref)
    tally = Hash.new(0)
    puts format("%-4s %-18s %-26s %-26s %s", "RQ", "claim", "measured",
                "paper (#{level})", "verdict")
    CLAIMS.each do |id, rq, text, rule, tol|
      v = ref.key?(id) && ref[id].nil? && m[id] ? "INFO" :
            verdict(rule, m[id], ref[id], tol)
      tally[v] += 1
      puts format("%-4s %-18s %-26s %-26s %-4s %s", rq, id, show(m[id]),
                  show(ref[id]), v, text)
    end
    puts tally.map { |k, n| "#{n} #{k}" }.join(", ")
    tally["WARN"].zero? ? 0 : 1
  end

  def main(argv)
    command, level = argv.shift(2)
    abort "usage: ae.rb filters|delegation|gcscripts|check LEVEL [DIR...]" \
      unless %w[smoke quick full].include?(level)
    case command
    when "filters" then puts flags(FILTERS.fetch(level))
    when "delegation" then puts flags(DELEGATION)
    when "gcscripts" then puts GCSCRIPTS.join(" ")
    when "check" then return check(level, argv)
    else abort "unknown command #{command}"
    end
    0
  end
end

exit AE.main(ARGV) if $PROGRAM_NAME == __FILE__
