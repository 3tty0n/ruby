# frozen_string_literal: true

require "fileutils"
require "json"

require_relative "plots"

module RPyYARVEvaluation
  # Paper figures rendered from named results directories, one pass, no
  # per-figure hand edits.  Each builder returns [svg paths, source columns].
  module Figures
    RSVG = "/opt/homebrew/bin/rsvg-convert"
    SERIES = [Plotter::BLUE, Plotter::ORANGE, Plotter::GREEN,
              Plotter::PURPLE, Plotter::RED].freeze
    # One colour per engine, shared by every figure that plots engines.
    ENGINE_COLORS = { "cruby" => Plotter::BLUE,
                      "cruby+yjit" => Plotter::ORANGE,
                      "cruby+zjit" => Plotter::GREEN,
                      "rpyyarv" => Plotter::PURPLE,
                      "rpyyarv-jit" => Plotter::RED }.freeze
    WARMUP_BENCHMARKS = %w[richards deltablue optcarrot railsbench
                           rubocop keyword_args].freeze
    WARMUP_ENGINES = %w[cruby cruby+yjit cruby+zjit rpyyarv-jit].freeze
    # Figure name => the manifest kinds its builder needs, first one required.
    SPECS = {
      "peak-performance" => %w[performance],
      "native-vs-delegated" => %w[delegation],
      "warmup" => %w[performance],
      "coverage" => %w[coverage performance],
      "boundary-crossing" => %w[boundary crossing],
      "memory" => %w[memory],
      "gc-nursery" => %w[nursery gc],
      "ablations" => %w[ablation],
      "mechanisms" => %w[mechanisms]
    }.freeze

    module_function

    def render(input_dirs, out_dir)
      FileUtils.mkdir_p(out_dir)
      inputs = input_dirs.map { |dir| describe(dir) }
      by_kind = {}
      inputs.each { |entry| (by_kind[entry["kind"]] ||= []) << entry["dir"] }
      figures = []
      skipped = {}
      SPECS.each do |name, kinds|
        dirs = kinds.to_h { |kind| [kind, by_kind[kind]&.last] }
        # Ablation runs are merged; every other kind takes the last directory.
        dirs["ablation_dirs"] = by_kind["ablation"] || []
        unless dirs[kinds.first]
          skipped[name] = "no #{kinds.first} results directory given"
          next
        end
        paths, columns = send(name.tr("-", "_"), dirs, out_dir)
        if paths.nil? || paths.empty?
          skipped[name] = "input files missing or empty"
          next
        end
        figures << { "name" => name,
                     "inputs" => kinds.flat_map { |kind|
                       kind == "ablation" ? by_kind[kind] : [dirs[kind]]
                     }.compact,
                     "source_columns" => columns,
                     "files" => paths.flat_map { |svg| [svg, to_pdf(svg)] }
                                     .compact.map { |p| File.basename(p) } }
      end
      write_manifest(out_dir, inputs, figures, skipped)
      figures
    end

    def describe(dir)
      path = File.expand_path(dir)
      manifest = JSON.parse(File.read(File.join(path, "manifest.json")))
      binaries = (manifest["engine_binaries"] || {}).transform_values do |v|
        v["sha256"]
      end
      { "dir" => path, "kind" => manifest["kind"],
        "git_commit" => manifest.dig("git", "commit"),
        "git_dirty" => manifest.dig("git", "dirty"),
        "engine_binaries" => binaries.compact }
    end

    def write_manifest(out_dir, inputs, figures, skipped)
      RPyYARVEvaluation.write_json(
        File.join(out_dir, "manifest.json"),
        "schema" => 1,
        "generated_at" => Time.now.utc.iso8601,
        "git" => RPyYARVEvaluation.git_metadata,
        "tools" => { "ruby" => RUBY_DESCRIPTION,
                     "rsvg_convert" => rsvg_version },
        "inputs" => inputs, "figures" => figures, "skipped" => skipped
      )
    end

    def rsvg_version
      return nil unless File.executable?(RSVG)

      out, ok = RPyYARVEvaluation.capture(RSVG, "--version")
      ok ? out : nil
    end

    def to_pdf(svg_path)
      return nil unless File.executable?(RSVG)

      pdf = svg_path.sub(/\.svg\z/, ".pdf")
      system(RSVG, "-f", "pdf", "-o", pdf, svg_path) ? pdf : nil
    end

    def read_csv(path)
      return [] unless path && File.file?(path)

      lines = File.readlines(path, chomp: true).reject(&:empty?)
      return [] if lines.empty?

      headers = Org.split(lines.first)
      lines[1..].map { |line| headers.zip(Org.split(line)).to_h }
    end

    def num(value)
      Float(value.to_s, exception: false)
    end

    def positive(value)
      value = num(value)
      value&.positive? ? value : nil
    end

    def geomean(values)
      Analyzer.geomean(values)
    end

    def percentile(values, fraction)
      sorted = values.compact.sort
      return nil if sorted.empty?

      sorted[[(sorted.size - 1) * fraction, 0].max.round]
    end

    def engine_color(engine, index)
      ENGINE_COLORS.fetch(engine) { SERIES[index % SERIES.size] }
    end

    def write_svg(out_dir, name, body)
      path = File.join(out_dir, name)
      File.write(path, body)
      path
    end

    # --- generic renderers ------------------------------------------------

    # cats: [{ label:, group: }]; series: [{ name:, color:, values: }] where a
    # value is a number, [value, low, high], or nil.
    def categorical_svg(title, x_label, y_label, cats, series, log: true,
                        unit: nil, cap: nil)
      count = [cats.size, 1].max
      width = [900, 190 + count * 22].max
      left = 92
      right = 70
      top = 78
      # Room for the 60-degree labels: 13px type, ~6.5px of drop per char.
      bottom = 60 + cats.map { |c| c[:label].to_s.size }.max.to_i * 6.5
      height = 420 + bottom
      pw = width - left - right
      ph = height - top - bottom
      flat = series.flat_map { |s| s[:values] }.flatten.compact
      flat = flat.select(&:positive?) if log
      return nil if flat.empty?

      if log
        low, high = Plotter.log_bounds(flat)
        ticks = Plotter.power_ticks(low, high)
        span = Math.log2(high) - Math.log2(low)
        y = ->(v) { top + (Math.log2(high) - Math.log2(v)) / span * ph }
        base = 1.0
      else
        low, high, ticks = Plotter.linear_axis(flat, cap: cap)
        y = ->(v) { top + ph * (1.0 - (v - low) / (high - low)) }
        base = 0.0
      end
      step = pw.to_f / count
      offset = [step / (series.size + 1), 7.0].min
      body = [Plotter.svg_header(width, height, title),
              Plotter.frame(left, top, pw, ph)]
      ticks.each do |tick|
        yy = y.call(tick)
        weight = log && tick == 1 ? 2 : 1
        body << Plotter.line(left, yy, left + pw, yy, Plotter::GRID, weight)
        label = log ? Plotter.format_ratio(tick) : format_tick(tick, unit)
        body << Plotter.text(left - 10, yy + 4, label, anchor: "end")
      end
      cats.each_with_index do |cat, index|
        x0 = left + (index + 0.5) * step
        if index.positive? && cat[:group] != cats[index - 1][:group]
          edge = left + index * step
          body << Plotter.line(edge, top, edge, top + ph, Plotter::MUTED, 1,
                               "4 4")
        end
        series.each_with_index do |serie, si|
          entry = serie[:values][index]
          next if entry.nil?

          value, lo, hi = Array(entry)
          next if value.nil? || (log && !value.positive?)

          xx = x0 + (si - (series.size - 1) / 2.0) * offset
          body << Plotter.line(xx, y.call(base), xx, y.call(value),
                               serie[:color], 1)
          if lo && hi && (!log || (lo.positive? && hi.positive?))
            body << Plotter.line(xx, y.call(lo), xx, y.call(hi),
                                 serie[:color], 1)
            body << Plotter.line(xx - 2.5, y.call(lo), xx + 2.5, y.call(lo),
                                 serie[:color], 1)
            body << Plotter.line(xx - 2.5, y.call(hi), xx + 2.5, y.call(hi),
                                 serie[:color], 1)
          end
          body << Plotter.marker(xx, y.call(value), 3.5, serie[:color], si)
        end
        body << rotated_tick(x0, top + ph + 12, cat[:label])
      end
      body << Plotter.axis_title(left + pw / 2, height - 14, x_label)
      body << Plotter.rotated_axis_title(20, top + ph / 2, y_label)
      body << series_legend(series, left + 6, 56)
      body << "</svg>\n"
      body.join("\n")
    end

    def format_tick(value, unit)
      binary = (value % 1024).zero?
      text = if unit.nil? && value.abs >= 8192 && binary
               scale = [[1 << 30, "G"], [1 << 20, "M"], [1 << 10, "K"]]
                       .find { |size, _| value.abs >= size }
               format("%g%s", value / scale[0], scale[1])
             elsif value.abs >= 100
               format("%.0f", value)
             else
               format("%.3g", value)
             end
      unit ? "#{text}#{unit}" : text
    end

    def rotated_tick(x, y, label)
      %(<text x="#{Plotter.fmt(x)}" y="#{y}" ) +
        %(transform="rotate(60 #{Plotter.fmt(x)} #{y})" ) +
        %(fill="#{Plotter::INK}" font-family="sans-serif" font-size="13" ) +
        %(text-anchor="start">#{Plotter.escape(label)}</text>)
    end

    def series_legend(series, x, y)
      xx = x
      series.each_with_index.map do |serie, index|
        entry = Plotter.marker(xx, y, 4.5, serie[:color], index) +
                Plotter.text(xx + 11, y + 5, serie[:name])
        xx += 36 + serie[:name].to_s.size * 8.5
        entry
      end.join("\n")
    end

    # curves: [{ name:, color:, points: [[x, y, label]] }]
    def lines_svg(title, x_label, y_label, curves, x_log: false, y_log: true,
                  unit: nil, cap: nil)
      width = 860
      height = 560
      left = 92
      right = 26
      top = 78
      bottom = 76
      pw = width - left - right
      ph = height - top - bottom
      xs = curves.flat_map { |c| c[:points].map { |p| p[0] } }
      ys = curves.flat_map { |c| c[:points].map { |p| p[1] } }.compact
      return nil if ys.empty?

      x = axis_mapper(xs, left, pw, x_log, false)
      y = axis_mapper(ys, top, ph, y_log, true, cap)
      # A y axis of ratios keeps 1x; an x axis of sizes keeps its own values.
      body = [Plotter.svg_header(width, height, title),
              Plotter.frame(left, top, pw, ph)]
      axis_ticks(ys, y_log, true, cap).each do |tick|
        yy = y.call(tick)
        weight = y_log && tick == 1 ? 2 : 1
        body << Plotter.line(left, yy, left + pw, yy, Plotter::GRID, weight)
        label = y_log ? Plotter.format_ratio(tick) : format_tick(tick, unit)
        body << Plotter.text(left - 10, yy + 4, label, anchor: "end")
      end
      axis_ticks(xs, x_log, false).each do |tick|
        xx = x.call(tick)
        body << Plotter.line(xx, top, xx, top + ph, Plotter::GRID, 1)
        body << Plotter.text(xx, top + ph + 20, format_tick(tick, nil),
                             anchor: "middle")
      end
      curves.each_with_index do |curve, ci|
        points = curve[:points].map do |px, py, _label|
          "#{Plotter.fmt(x.call(px))},#{Plotter.fmt(y.call(py))}"
        end.join(" ")
        body << %(<polyline points="#{points}" fill="none" ) +
                %(stroke="#{curve[:color]}" stroke-width="2"/>)
        curve[:points].each do |px, py, label|
          body << Plotter.marker(x.call(px), y.call(py), 3.5, curve[:color],
                                 ci)
          next unless label

          body << Plotter.text(x.call(px), y.call(py) - 10, label,
                               anchor: "middle", color: Plotter::MUTED)
        end
      end
      body << Plotter.axis_title(left + pw / 2, height - 16, x_label)
      body << Plotter.rotated_axis_title(20, top + ph / 2, y_label)
      body << series_legend(curves, left + 6, 56)
      body << "</svg>\n"
      body.join("\n")
    end

    def axis_mapper(values, offset, length, log, invert, cap = nil)
      if log
        low, high = axis_bounds(values, true, invert)
        span = Math.log(high) - Math.log(low)
        return lambda do |v|
          pos = (Math.log(v) - Math.log(low)) / span * length
          offset + (invert ? length - pos : pos)
        end
      end
      low, high = axis_bounds(values, false, invert, cap)
      lambda do |v|
        pos = (v - low) / (high - low) * length
        offset + (invert ? length - pos : pos)
      end
    end

    # Too many distinct values to label one tick each: fall back to decades.
    def wide?(values)
      values.uniq.size > 8
    end

    def axis_bounds(values, log, ratio = false, cap = nil)
      positives = values.select(&:positive?)
      return Plotter.log_bounds(positives) if log && ratio
      return Plotter.decade_bounds(positives) if log && wide?(positives)
      return [positives.min / 1.7, positives.max * 1.7] if log

      linear_axis(values, cap)[0, 2]
    end

    def axis_ticks(values, log, ratio = false, cap = nil)
      if log && ratio
        return Plotter.power_ticks(*axis_bounds(values, log, true))
      end
      if log
        return Plotter.decade_ticks(*axis_bounds(values, true)) if wide?(values)

        return values.uniq.sort
      end

      linear_axis(values, cap)[2]
    end

    def linear_axis(values, cap)
      integral = values.all? { |value| value == value.round }
      Plotter.linear_axis(values, cap: cap, integral: integral)
    end

    # --- figure builders --------------------------------------------------

    def measurement_table(rows, key = "median_ms")
      table = Hash.new { |hash, k| hash[k] = {} }
      rows.each do |row|
        value = positive(row[key])
        next unless value

        table[[row["suite"], row["benchmark"]]][row["engine"]] = value
      end
      table
    end

    def sorted_cats(table)
      table.keys.sort_by { |suite, bench| [suite, bench] }
    end

    def peak_performance(dirs, out_dir)
      csv = File.join(dirs["performance"], "measurements.csv")
      table = measurement_table(read_csv(csv))
      return nil if table.empty?

      keys = sorted_cats(table)
      groups = %w[awfy ruby-bench all]
      labels = { "rpyyarv" => "RPyYARV (interpreter)",
                 "rpyyarv-jit" => "RPyYARV JIT" }
      paths = [["cruby", "CRuby"], ["cruby+yjit", "YJIT"]].map do |ref, name|
        cats = keys.map { |suite, bench| { label: bench, group: suite } }
        cats += groups.map { |g| { label: "geomean #{g}", group: "z" } }
        series = labels.keys.each_with_index.map do |engine, index|
          values = keys.map do |key|
            row = table[key]
            row[engine] && row[ref] ? row[engine] / row[ref] : nil
          end
          summary = groups.map do |group|
            scoped = keys.each_index.select do |i|
              group == "all" || keys[i][0] == group
            end
            geomean(scoped.filter_map { |i| values[i] })
          end
          { name: labels[engine], color: engine_color(engine, index),
            values: values + summary }
        end
        body = categorical_svg(
          "Execution time relative to #{name} (lower is faster)",
          "Benchmark (AWFY, then ruby-bench, then geometric means)",
          "Time / #{name} time (log scale)", cats, series
        )
        write_svg(out_dir, "peak-vs-#{ref.tr('+', '-')}.svg", body)
      end
      [paths, %w[measurements.csv:suite benchmark engine median_ms]]
    end

    def native_vs_delegated(dirs, out_dir)
      rows = read_csv(File.join(dirs["delegation"], "delegation.csv"))
      return nil if rows.empty?

      engines = rows.map { |row| row["engine"] }.uniq
      order = rows.select { |row| row["engine"] == "rpyyarv-jit" }
                  .sort_by { |row| -num(row["native_penalty"]).to_f }
                  .map { |row| row["benchmark"] }
      order |= rows.map { |row| row["benchmark"] }
      index = rows.to_h { |row| [[row["benchmark"], row["engine"]], row] }
      cats = order.map { |bench| { label: bench, group: "gem" } }
      cats << { label: "geomean", group: "z" }
      series = engines.each_with_index.map do |engine, position|
        values = order.map do |bench|
          row = index[[bench, engine]]
          native = row && positive(row["native_ms"])
          delegated = row && positive(row["delegated_ms"])
          native && delegated ? native / delegated : nil
        end
        { name: engine, color: engine_color(engine, position),
          values: values + [geomean(values.compact)] }
      end
      body = categorical_svg(
        "Native gem execution relative to delegating the gem to CRuby",
        "Gem benchmark", "Native time / delegated time (log scale)",
        cats, series
      )
      [[write_svg(out_dir, "native-vs-delegated.svg", body)],
       %w[delegation.csv:benchmark engine native_ms delegated_ms]]
    end

    def warmup(dirs, out_dir)
      raw_path = File.join(dirs["performance"], "raw.json")
      return nil unless File.file?(raw_path)

      raw = JSON.parse(File.read(raw_path))
      paths = WARMUP_BENCHMARKS.filter_map do |bench|
        curves = WARMUP_ENGINES.each_with_index.filter_map do |engine, index|
          key = raw.keys.find do |k|
            parts = k.split("/", 3)
            parts[1] == bench && parts[2] == engine
          end
          points = key && warmup_points(raw[key])
          next unless points && points.size > 1

          { name: engine, color: engine_color(engine, index),
            points: points }
        end
        next if curves.size < 2

        body = lines_svg(
          "Warm-up on #{bench}: iteration time versus steady state",
          "Iteration within a fresh process",
          "Time / that engine's steady median (log scale)", curves
        )
        body && write_svg(out_dir, "warmup-#{bench}.svg", body)
      end
      rows = Analyzer.warmup_rows(raw)
      paths += [time_to_stable_svg(rows, out_dir),
                classification_svg(rows, out_dir)].compact
      [paths, %w[raw.json:raw_iterations warmed_at]]
    end

    # Sorted curve of every process's time to a steady state, per engine.
    def time_to_stable_svg(rows, out_dir)
      curves = WARMUP_ENGINES.each_with_index.filter_map do |engine, index|
        times = rows.select { |row| row["engine"] == engine }
                    .filter_map { |row| positive(row["time_to_stable_ms"]) }
        next if times.size < 2

        points = (0..40).map do |step|
          [percentile(times, step / 40.0), step / 40.0 * 100.0]
        end
        { name: engine, color: engine_color(engine, index), points: points }
      end
      return nil if curves.empty?

      body = lines_svg("Time to a steady state across all benchmarks",
                       "Cumulative time to the steady state (ms, log scale)",
                       "Processes at or below that time (%)", curves,
                       x_log: true, y_log: false, cap: 100)
      body && write_svg(out_dir, "warmup-time-to-stable.svg", body)
    end

    def classification_svg(rows, out_dir)
      counts = WARMUP_ENGINES.map do |engine|
        group = rows.select { |row| row["engine"] == engine }
        [engine, Analyzer::CLASSIFICATIONS.map do |name|
          group.count { |row| row["classification"] == name }
        end]
      end
      return nil if counts.all? { |_, values| values.sum.zero? }

      body = stacked_bars_svg(
        "Warm-up classification per engine (Barrett et al. categories)",
        "Engine", "Processes", counts, Analyzer::CLASSIFICATIONS
      )
      body && write_svg(out_dir, "warmup-classification.svg", body)
    end

    # bars: [[label, [count per category]]]
    def stacked_bars_svg(title, x_label, y_label, bars, categories)
      width = 860
      height = 480
      left = 92
      top = 78
      pw = width - left - 26
      ph = height - top - 76
      total = bars.map { |_, values| values.sum }.max
      return nil unless total&.positive?

      _low, total, ticks = Plotter.linear_axis([0, total], integral: true)
      y = ->(v) { top + ph * (1.0 - v.to_f / total) }
      step = pw.to_f / [bars.size, 1].max
      body = [Plotter.svg_header(width, height, title),
              Plotter.frame(left, top, pw, ph)]
      ticks.each do |tick|
        body << Plotter.line(left, y.call(tick), left + pw, y.call(tick),
                             Plotter::GRID, 1)
        body << Plotter.text(left - 10, y.call(tick) + 4,
                             format("%.0f", tick), anchor: "end")
      end
      bars.each_with_index do |(label, values), index|
        base = 0
        xx = left + (index + 0.5) * step
        values.each_with_index do |value, ci|
          next if value.zero?

          body << Plotter.line(xx, y.call(base), xx, y.call(base + value),
                               SERIES[ci % SERIES.size], [step / 3, 40].min)
          base += value
        end
        body << Plotter.text(xx, top + ph + 20, label, anchor: "middle")
      end
      series = categories.each_with_index.map do |name, ci|
        { name: name, color: SERIES[ci % SERIES.size] }
      end
      body << Plotter.axis_title(left + pw / 2, height - 14, x_label)
      body << Plotter.rotated_axis_title(20, top + ph / 2, y_label)
      body << series_legend(series, left + 6, 56)
      body << "</svg>\n"
      body.join("\n")
    end

    def warmup_points(entry)
      warmed = entry["warmed_at"] || []
      iterations = entry["raw_iterations"] || []
      curves = iterations.each_with_index.filter_map do |samples, process|
        steady = samples[(warmed[process] || 0)..] || []
        center = Plotter.median_number(steady)
        next unless center&.positive?

        samples.map { |value| value / center }
      end
      return nil if curves.empty?

      length = curves.map(&:size).min
      (0...length).map do |index|
        [index + 1, Plotter.median_number(curves.map { |c| c[index] })]
      end
    end

    def coverage(dirs, out_dir)
      rows = read_csv(File.join(dirs["coverage"], "coverage.csv"))
      return nil if rows.empty?

      files = dirs["performance"] ? file_fractions(dirs["performance"]) : {}
      scored = rows.map do |row|
        match = row["iseqs"].to_s.match(%r{\A(\d+)/(\d+)\z})
        pct = match && match[2].to_i.positive? ?
          match[1].to_f / match[2].to_i * 100 : nil
        [row["benchmark"], row["status"].to_s.empty? ? "other" : row["status"],
         pct, files[row["benchmark"]]]
      end.sort_by { |bench, status, pct, _| [status, -(pct || -1.0), bench] }
      cats = scored.map do |bench, status, _, _|
        { label: bench, group: status }
      end
      series = [{ name: "Native ISeqs (%)", color: SERIES[0],
                  values: scored.map { |_, _, pct, _| pct } }]
      unless files.empty?
        series << { name: "Natively loaded files (%)", color: SERIES[1],
                    values: scored.map { |_, _, _, share| share } }
      end
      body = categorical_svg(
        "Compatibility coverage: share of each benchmark run natively",
        "Benchmark (grouped by harness status)", "Percent of the benchmark",
        cats, series, log: false, unit: "%", cap: 100
      )
      [[write_svg(out_dir, "coverage.svg", body)],
       %w[coverage.csv:benchmark status iseqs
          measurements.csv:files_native files_delegated]]
    end

    def file_fractions(performance_dir)
      rows = read_csv(File.join(performance_dir, "measurements.csv"))
      rows.each_with_object({}) do |row, all|
        next unless row["engine"] == "rpyyarv-jit"

        native = num(row["files_native"])
        delegated = num(row["files_delegated"])
        next unless native && delegated && (native + delegated).positive?

        all[row["benchmark"]] = native / (native + delegated) * 100
      end
    end

    def boundary_crossing(dirs, out_dir)
      paths = []
      rows = read_csv(File.join(dirs["boundary"], "boundary.csv"))
      unless rows.empty?
        sorted = rows.sort_by { |row| -num(row["cruby_share"]).to_f }
        cats = sorted.map { |row| { label: row["benchmark"], group: "b" } }
        series = [{ name: "CRuby share of sends (%)", color: SERIES[0],
                    values: sorted.map { |row|
                      share = num(row["cruby_share"])
                      share && share * 100
                    } }]
        body = categorical_svg(
          "Residual delegation: share of sends that reach CRuby",
          "Benchmark", "CRuby sends / all sends", cats, series,
          log: false, unit: "%", cap: 100
        )
        paths << write_svg(out_dir, "boundary.svg", body) if body
      end
      crossing = dirs["crossing"] &&
                 read_csv(File.join(dirs["crossing"], "crossing.csv"))
      if crossing && !crossing.empty?
        kernels = crossing.map { |row| row["kernel"] }.uniq - ["empty"]
        engines = crossing.map { |row| row["engine"] }.uniq
        index = crossing.to_h { |row| [[row["kernel"], row["engine"]], row] }
        cats = kernels.map { |kernel| { label: kernel, group: "k" } }
        series = engines.each_with_index.map do |engine, position|
          { name: engine, color: engine_color(engine, position),
            values: kernels.map { |kernel|
              num(index.dig([kernel, engine], "net_ns"))
            } }
        end
        body = categorical_svg(
          "Cost of one boundary send, net of an empty loop",
          "Micro-kernel", "Nanoseconds per send", cats, series,
          log: false, unit: " ns"
        )
        paths << write_svg(out_dir, "crossing.svg", body) if body
      end
      [paths, %w[boundary.csv:benchmark cruby_share
                 crossing.csv:kernel engine net_ns]]
    end

    def memory(dirs, out_dir)
      rows = read_csv(File.join(dirs["memory"], "memory.csv"))
      table = measurement_table(rows, "peak_rss_mb")
      return nil if table.empty?

      keys = sorted_cats(table)
      pairs = [%w[rpyyarv cruby], %w[rpyyarv-jit cruby],
               ["rpyyarv-jit", "cruby+yjit"]]
      cats = keys.map { |suite, bench| { label: bench, group: suite } }
      cats << { label: "geomean", group: "z" }
      series = pairs.each_with_index.map do |(engine, reference), index|
        values = keys.map do |key|
          row = table[key]
          row[engine] && row[reference] ? row[engine] / row[reference] : nil
        end
        { name: "#{engine} / #{reference}", color: SERIES[index],
          values: values + [geomean(values.compact)] }
      end
      body = categorical_svg(
        "Peak resident set size relative to CRuby",
        "Benchmark", "Peak RSS ratio (log scale)", cats, series
      )
      [[write_svg(out_dir, "memory.svg", body)],
       %w[memory.csv:suite benchmark engine peak_rss_mb]]
    end

    def gc_nursery(dirs, out_dir)
      paths = []
      rows = read_csv(File.join(dirs["nursery"], "nursery.csv"))
      times = read_csv(File.join(dirs["nursery"],
                                 "nursery-measurements.csv"))
      by_size = times.to_h { |row| [row["nursery_bytes"], row] }
      unless rows.empty?
        points = rows.sort_by { |row| num(row["nursery_bytes"]).to_f }
                     .filter_map do |row|
          seconds = positive(by_size.dig(row["nursery_bytes"], "median_ms"))
          next unless seconds

          [num(row["nursery_bytes"]), seconds / 1000.0,
           "#{row['failures']}/#{row['trials']} failed"]
        end
        body = points.size > 1 && lines_svg(
          "Nursery dose-response: run time and failures versus nursery size",
          "PYPY_GC_NURSERY (bytes, log scale)", "Median run time (seconds)",
          [{ name: "hexapdf under rpyyarv-jit", color: SERIES[0],
             points: points }], x_log: true, y_log: false, unit: " s"
        )
        paths << write_svg(out_dir, "nursery.svg", body) if body
      end
      gc = dirs["gc"] ? read_csv(File.join(dirs["gc"], "gc.csv")) : []
      unless gc.empty?
        sorted = gc.sort_by { |row| -num(row["malloc_limit"]).to_f }
        cats = sorted.map do |row|
          { label: "malloc limit #{row['malloc_limit']}", group: "gc" }
        end
        series = %w[ok skipped failed].each_with_index.map do |field, index|
          { name: "#{field} cases", color: SERIES[index],
            values: sorted.map { |row| num(row[field]) } }
        end
        body = categorical_svg(
          "GC stress: correctness cases per RUBY_GC_MALLOC_LIMIT",
          "CRuby malloc limit", "Test cases", cats, series, log: false
        )
        paths << write_svg(out_dir, "gc-stress.svg", body) if body
      end
      [paths, %w[nursery.csv:nursery_bytes trials failures
                 nursery-measurements.csv:median_ms gc.csv:ok skipped failed]]
    end

    def ablations(dirs, out_dir)
      rows = dirs["ablation_dirs"].flat_map do |dir|
        read_csv(File.join(dir, "ablation-measurements.csv"))
      end
      return nil if rows.empty?

      table = Hash.new { |hash, key| hash[key] = {} }
      rows.each do |row|
        next unless row["engine"] == "rpyyarv-jit"

        value = positive(row["median_ms"])
        next unless value

        table[[row["suite"], row["benchmark"]]][row["ablation"]] = value
      end
      names = rows.map { |row| row["ablation"] }.uniq - ["baseline"]
      # A geomean over survivors is a lie without the count that survived.
      cats = names.map do |name|
        timed = table.count { |_key, e| e["baseline"] && e[name] }
        { label: "#{name} (#{timed}/#{table.size} timed)", group: "a" }
      end
      suites = %w[awfy ruby-bench all]
      series = suites.each_with_index.map do |suite, index|
        values = names.map do |name|
          ratios = table.filter_map do |(row_suite, _bench), entry|
            next unless suite == "all" || row_suite == suite
            next unless entry["baseline"] && entry[name]

            entry[name] / entry["baseline"]
          end
          next nil if ratios.empty?

          [geomean(ratios), percentile(ratios, 0.1), percentile(ratios, 0.9)]
        end
        { name: "#{suite} geomean", color: SERIES[index], values: values }
      end
      body = categorical_svg(
        "Runtime ablations: time relative to the unablated baseline",
        "Ablation (whiskers: 10th to 90th percentile benchmark)",
        "Time / baseline (log scale)", cats, series
      )
      [[write_svg(out_dir, "ablations.svg", body)],
       %w[ablation-measurements.csv:ablation suite benchmark engine
          median_ms]]
    end

    def mechanisms(dirs, out_dir)
      path = File.join(dirs["mechanisms"], "mechanisms.json")
      return nil unless File.file?(path)

      [Plotter.plot_mechanisms(path, out_dir),
       %w[mechanisms.json:bridges_per_loop cruby_sends_per_iteration
          compile_fraction performance_jit_over_yjit]]
    rescue StandardError
      nil
    end
  end
end
