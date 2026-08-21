# frozen_string_literal: true

require "cgi"
require "fileutils"
require "json"

module RPyYARVEvaluation
  module Plotter
    BLUE = "#0072b2"
    ORANGE = "#e69f00"
    GREEN = "#009e73"
    RED = "#d55e00"
    PURPLE = "#cc79a7"
    GRID = "#d0d7de"
    INK = "#24292f"
    MUTED = "#57606a"

    module_function

    def plot(raw_path, out_dir)
      raw = JSON.parse(File.read(raw_path))
      FileUtils.mkdir_p(out_dir)
      paths = []
      references = EvaluationConfig::REFERENCES.dup
      measured_engines(raw).each do |engine|
        next if references.value?(engine)
        next if %w[rpyyarv rpyyarv-jit].include?(engine)

        references[engine] = engine
      end
      references.each do |label, engine|
        points = points_from(raw, engine)
        next if points.empty?

        file_label = label.gsub(/[^A-Za-z0-9_.-]/, "_")
        ratio_path = File.join(out_dir, "ratio-to-#{file_label}.svg")
        scatter_path = File.join(out_dir, "scatter-#{file_label}.svg")
        File.write(ratio_path, ratio_svg(points, label))
        File.write(scatter_path, scatter_svg(points, label))
        paths.concat([ratio_path, scatter_path])
      end
      curves = warmup_curves(raw)
      unless curves.empty?
        path = File.join(out_dir, "warmup-normalized.svg")
        File.write(path, warmup_svg(curves))
        paths << path
      end
      raise "no paired RPyYARV JIT/reference measurements" if paths.empty?

      paths
    end

    def warmup_curves(raw)
      engines = %w[cruby cruby+yjit cruby+zjit rpyyarv-jit]
      samples = Hash.new { |hash, key| hash[key] = [] }
      raw.each do |key, value|
        engine = key.split("/", 3)[2]
        next unless engines.include?(engine)

        warmed = value["warmed_at"] || []
        (value["raw_iterations"] || []).each_with_index do |curve, process|
          steady = curve[(warmed[process] || 0)..] || []
          center = median_number(steady)
          next unless center && center.positive?

          samples[engine] << curve.map { |sample| sample / center }
        end
      end
      samples.transform_values do |curves|
        length = curves.map(&:size).min
        length.times.map do |index|
          values = curves.map { |curve| curve[index] }.compact
          median_number(values)
        end
      end
    end

    def median_number(values)
      sorted = values.compact.sort
      return nil if sorted.empty?

      middle = sorted.size / 2
      sorted.size.odd? ? sorted[middle] :
        (sorted[middle - 1] + sorted[middle]) / 2.0
    end

    def warmup_svg(curves)
      width = 820
      height = 560
      left = 78
      right = 24
      top = 54
      bottom = 76
      plot_width = width - left - right
      plot_height = height - top - bottom
      count = curves.values.map(&:size).max
      values = curves.values.flatten.compact.select(&:positive?)
      low, high = log_bounds(values)
      x = lambda do |index|
        left + index.to_f / [count - 1, 1].max * plot_width
      end
      y = lambda do |value|
        top + (Math.log2(high) - Math.log2(value)) /
          (Math.log2(high) - Math.log2(low)) * plot_height
      end
      body = []
      body << svg_header(width, height,
                         "Median warm-up relative to each process steady median")
      body << frame(left, top, plot_width, plot_height)
      power_ticks(low, high).each do |tick|
        yy = y.call(tick)
        body << line(left, yy, left + plot_width, yy, GRID,
                     tick == 1 ? 2 : 1)
        body << text(left - 10, yy + 4, format_ratio(tick), anchor: "end")
      end
      curves.each_with_index do |(engine, curve), series|
        points = curve.each_with_index.map do |value, index|
          "#{fmt(x.call(index))},#{fmt(y.call(value))}"
        end.join(" ")
        body << %(<polyline points="#{points}" fill="none" ) +
                %(stroke="#{engine_color(series)}" stroke-width="2"/>)
      end
      body << axis_title(left + plot_width / 2, height - 18,
                         "Iteration within a fresh process")
      body << rotated_axis_title(18, top + plot_height / 2,
                                  "Time / steady median (log scale)")
      body << engine_legend(curves.keys, width - 460, 22)
      body << "</svg>\n"
      body.join("\n")
    end

    def engine_color(index)
      [BLUE, ORANGE, GREEN, PURPLE, RED][index % 5]
    end

    def engine_legend(engines, x, y)
      engines.each_with_index.map do |engine, index|
        xx = x + index * 105
        circle(xx, y, 4, engine_color(index)) +
          text(xx + 8, y + 4, engine)
      end.join("\n")
    end

    def measured_engines(raw)
      raw.keys.map { |key| key.split("/", 3)[2] }.compact.uniq
    end

    def plot_mechanisms(raw_path, out_dir)
      rows = JSON.parse(File.read(raw_path))
      FileUtils.mkdir_p(out_dir)
      specs = [
        ["bridges_per_loop", "fragmentation-vs-yjit-gap.svg",
         "Trace fragmentation versus YJIT gap", "Compiled bridges per loop"],
        ["cruby_sends_per_iteration", "boundary-vs-yjit-gap.svg",
         "CRuby boundary traffic versus YJIT gap",
         "CRuby sends per benchmark iteration"]
      ]
      paths = specs.each_with_object([]) do |(key, filename, title, x_label), all|
        points = mechanism_points(rows, key)
        next if points.empty?

        path = File.join(out_dir, filename)
        File.write(path, mechanism_scatter_svg(points, title, x_label))
        all << path
      end
      compile_rows = rows.select do |row|
        positive(row["compile_fraction"])
      end
      unless compile_rows.empty?
        path = File.join(out_dir, "compile-tax.svg")
        File.write(path, compile_tax_svg(compile_rows))
        paths << path
      end
      raise "no mechanism metrics can be plotted" if paths.empty?

      paths
    end

    def mechanism_points(rows, x_key)
      rows.each_with_object([]) do |row, points|
        x = row[x_key]
        y = positive(row["performance_jit_over_yjit"])
        next unless x.is_a?(Numeric) && x >= 0 && y

        points << { x: x.to_f, y: y, suite: row["suite"],
                    benchmark: row["benchmark"] }
      end
    end

    def mechanism_scatter_svg(points, title, x_label)
      width = 820
      height = 650
      left = 86
      right = 30
      top = 54
      bottom = 76
      plot_width = width - left - right
      plot_height = height - top - bottom
      max_x = [points.map { |point| point[:x] }.max, 1.0].max
      x_max_log = Math.log10(1.0 + max_x)
      low_y, high_y = log_bounds(points.map { |point| point[:y] })
      x = ->(value) { left + Math.log10(1.0 + value) / x_max_log * plot_width }
      y = lambda do |value|
        top + (Math.log2(high_y) - Math.log2(value)) /
          (Math.log2(high_y) - Math.log2(low_y)) * plot_height
      end
      body = []
      body << svg_header(width, height, title)
      body << frame(left, top, plot_width, plot_height)
      mechanism_x_ticks(max_x).each do |tick|
        xx = x.call(tick)
        body << line(xx, top, xx, top + plot_height, GRID, 1)
        body << text(xx, top + plot_height + 22, format("%g", tick),
                     anchor: "middle")
      end
      power_ticks(low_y, high_y).each do |tick|
        yy = y.call(tick)
        body << line(left, yy, left + plot_width, yy, GRID,
                     tick == 1 ? 2 : 1)
        body << text(left - 10, yy + 4, format_ratio(tick), anchor: "end")
      end
      points.each do |point|
        label = escape("#{point[:suite]}/#{point[:benchmark]}")
        body << %(<circle cx="#{fmt(x.call(point[:x]))}" ) +
                %(cy="#{fmt(y.call(point[:y]))}" r="5" ) +
                %(fill="#{suite_color(point[:suite])}" fill-opacity="0.78">) +
                "<title>#{label}: x=#{fmt(point[:x])}, " +
                "RPyYARV/YJIT=#{fmt(point[:y])}</title></circle>"
      end
      body << axis_title(left + plot_width / 2, height - 18,
                         "#{x_label} (log1p scale)")
      body << rotated_axis_title(20, top + plot_height / 2,
                                  "RPyYARV JIT / YJIT time")
      body << legend(width - 235, 22)
      body << "</svg>\n"
      body.join("\n")
    end

    def mechanism_x_ticks(maximum)
      ticks = [0.0]
      power = 0
      while 10.0**power <= maximum
        ticks << 10.0**power
        power += 1
      end
      ticks << maximum unless ticks.include?(maximum)
      ticks.uniq.sort
    end

    def compile_tax_svg(rows)
      width = [960, 150 + rows.size * 20].max
      height = 560
      left = 78
      right = 24
      top = 54
      bottom = 190
      plot_width = width - left - right
      plot_height = height - top - bottom
      maximum = [rows.map { |row| row["compile_fraction"] }.max, 0.1].max
      maximum = (maximum * 10).ceil / 10.0
      x_step = plot_width.to_f / rows.size
      y = ->(value) { top + plot_height * (1.0 - value / maximum) }
      body = []
      body << svg_header(width, height,
                         "RPython tracing and backend compilation tax")
      body << frame(left, top, plot_width, plot_height)
      5.times do |index|
        tick = maximum * index / 4.0
        yy = y.call(tick)
        body << line(left, yy, left + plot_width, yy, GRID, 1)
        body << text(left - 10, yy + 4, format("%.0f%%", tick * 100),
                     anchor: "end")
      end
      rows.each_with_index do |row, index|
        xx = left + (index + 0.5) * x_step
        value = row["compile_fraction"]
        body << line(xx, y.call(0), xx, y.call(value),
                     suite_color(row["suite"]), 3)
        label = escape(row["benchmark"])
        body << %(<text x="#{fmt(xx)}" y="#{top + plot_height + 12}" ) +
                %(transform="rotate(60 #{fmt(xx)} #{top + plot_height + 12})" ) +
                %(fill="#{INK}" font-size="10" text-anchor="start">) +
                "#{label}</text>"
      end
      body << axis_title(width / 2, height - 12, "Benchmark")
      body << rotated_axis_title(18, top + plot_height / 2,
                                  "(Tracing + Backend) / total process time")
      body << legend(width - 235, 22)
      body << "</svg>\n"
      body.join("\n")
    end

    def points_from(raw, reference_engine)
      grouped = Hash.new { |hash, key| hash[key] = {} }
      raw.each do |key, value|
        suite, benchmark, engine = key.split("/", 3)
        time = positive(value["median"])
        grouped[[suite, benchmark]][engine] = time if time
      end
      grouped.each_with_object([]) do |((suite, benchmark), engines), points|
        jit = engines["rpyyarv-jit"]
        reference = engines[reference_engine]
        next unless jit && reference

        points << { suite: suite, benchmark: benchmark, jit: jit,
                    reference: reference, ratio: jit / reference }
      end.sort_by { |point| [point[:suite], point[:benchmark]] }
    end

    def positive(value)
      value.is_a?(Numeric) && value.positive? ? value.to_f : nil
    end

    def ratio_svg(points, reference_label)
      width = [960, 150 + points.size * 20].max
      height = 650
      left = 78
      right = 24
      top = 54
      bottom = 205
      plot_width = width - left - right
      plot_height = height - top - bottom
      low, high = log_bounds(points.map { |point| point[:ratio] })
      ticks = power_ticks(low, high)
      x_step = plot_width.to_f / points.size
      y = lambda do |value|
        top + (Math.log2(high) - Math.log2(value)) /
          (Math.log2(high) - Math.log2(low)) * plot_height
      end
      body = []
      reference_name = display_name(reference_label)
      body << svg_header(width, height,
                         "RPyYARV JIT execution time relative to #{reference_name}")
      body << frame(left, top, plot_width, plot_height)
      ticks.each do |tick|
        yy = y.call(tick)
        body << line(left, yy, left + plot_width, yy, GRID, tick == 1 ? 2 : 1)
        body << text(left - 10, yy + 4, format_ratio(tick), anchor: "end")
      end
      points.each_with_index do |point, index|
        x = left + (index + 0.5) * x_step
        color = suite_color(point[:suite])
        body << line(x, y.call(1), x, y.call(point[:ratio]), color, 1)
        body << circle(x, y.call(point[:ratio]), 3.5, color)
        label = escape(point[:benchmark])
        body << %(<text x="#{fmt(x)}" y="#{top + plot_height + 12}" ) +
                %(transform="rotate(60 #{fmt(x)} #{top + plot_height + 12})" ) +
                %(fill="#{INK}" font-size="10" text-anchor="start">) +
                "#{label}</text>"
      end
      body << axis_title(width / 2, height - 12, "Benchmark")
      body << rotated_axis_title(18, top + plot_height / 2,
                                  "Execution time / #{reference_name} time")
      body << legend(width - 235, 22)
      body << "</svg>\n"
      body.join("\n")
    end

    def scatter_svg(points, reference_label)
      width = 820
      height = 720
      left = 86
      right = 30
      top = 54
      bottom = 76
      plot_width = width - left - right
      plot_height = height - top - bottom
      values = points.flat_map { |point| [point[:jit], point[:reference]] }
      low, high = decade_bounds(values)
      ticks = decade_ticks(low, high)
      x = ->(value) { log_position(value, low, high, left, plot_width) }
      y = lambda do |value|
        top + plot_height - log_position(value, low, high, 0, plot_height)
      end
      body = []
      reference_name = display_name(reference_label)
      body << svg_header(width, height,
                         "RPyYARV JIT versus #{reference_name}")
      body << frame(left, top, plot_width, plot_height)
      ticks.each do |tick|
        xx = x.call(tick)
        yy = y.call(tick)
        body << line(xx, top, xx, top + plot_height, GRID, 1)
        body << line(left, yy, left + plot_width, yy, GRID, 1)
        body << text(xx, top + plot_height + 22, format_ms(tick),
                     anchor: "middle")
        body << text(left - 10, yy + 4, format_ms(tick), anchor: "end")
      end
      body << line(x.call(low), y.call(low), x.call(high), y.call(high),
                   MUTED, 2, "6 5")
      points.each do |point|
        label = escape("#{point[:suite]}/#{point[:benchmark]}")
        body << %(<circle cx="#{fmt(x.call(point[:reference]))}" ) +
                %(cy="#{fmt(y.call(point[:jit]))}" r="5" ) +
                %(fill="#{suite_color(point[:suite])}" fill-opacity="0.76">) +
                "<title>#{label}: RPyYARV #{fmt(point[:jit])} ms, " +
                "#{reference_name} #{fmt(point[:reference])} ms</title></circle>"
      end
      body << axis_title(left + plot_width / 2, height - 18,
                         "#{reference_name} median time (ms, log scale)")
      body << rotated_axis_title(20, top + plot_height / 2,
                                  "RPyYARV JIT median time (ms, log scale)")
      body << text(x.call(high) - 8, y.call(high) + 18, "equal time",
                   anchor: "end", color: MUTED)
      body << legend(width - 235, 22)
      body << "</svg>\n"
      body.join("\n")
    end

    def svg_header(width, height, title)
      %(<?xml version="1.0" encoding="UTF-8"?>\n) +
        %(<svg xmlns="http://www.w3.org/2000/svg" width="#{width}" ) +
        %(height="#{height}" viewBox="0 0 #{width} #{height}" ) +
        %(role="img" aria-labelledby="title desc">\n) +
        %(<title id="title">#{escape(title)}</title>\n) +
        %(<desc id="desc">Lower values indicate faster execution.</desc>\n) +
        %(<rect width="100%" height="100%" fill="white"/>\n) +
        %(<text x="24" y="31" fill="#{INK}" font-family="sans-serif" ) +
        %(font-size="18" font-weight="600">#{escape(title)}</text>)
    end

    def frame(x, y, width, height)
      %(<rect x="#{x}" y="#{y}" width="#{width}" height="#{height}" ) +
        %(fill="none" stroke="#{INK}" stroke-width="1"/>)
    end

    def line(x1, y1, x2, y2, color, width, dash = nil)
      attrs = dash ? %( stroke-dasharray="#{dash}") : ""
      %(<line x1="#{fmt(x1)}" y1="#{fmt(y1)}" x2="#{fmt(x2)}" ) +
        %(y2="#{fmt(y2)}" stroke="#{color}" stroke-width="#{width}"#{attrs}/>)
    end

    def circle(x, y, radius, color)
      %(<circle cx="#{fmt(x)}" cy="#{fmt(y)}" r="#{radius}" ) +
        %(fill="#{color}"/>)
    end

    def text(x, y, value, anchor: "start", color: INK)
      %(<text x="#{fmt(x)}" y="#{fmt(y)}" fill="#{color}" ) +
        %(font-family="sans-serif" font-size="11" ) +
        %(text-anchor="#{anchor}">#{escape(value)}</text>)
    end

    def axis_title(x, y, value)
      %(<text x="#{fmt(x)}" y="#{fmt(y)}" fill="#{INK}" ) +
        %(font-family="sans-serif" font-size="12" text-anchor="middle">) +
        "#{escape(value)}</text>"
    end

    def rotated_axis_title(x, y, value)
      %(<text x="#{fmt(x)}" y="#{fmt(y)}" fill="#{INK}" ) +
        %(font-family="sans-serif" font-size="12" text-anchor="middle" ) +
        %(transform="rotate(-90 #{fmt(x)} #{fmt(y)})">) +
        "#{escape(value)}</text>"
    end

    def legend(x, y)
      [%w[ruby-bench], %w[awfy]].flatten.each_with_index.map do |suite, index|
        xx = x + index * 112
        circle(xx, y, 4, suite_color(suite)) +
          text(xx + 9, y + 4, suite)
      end.join("\n")
    end

    def suite_color(suite)
      suite == "awfy" ? ORANGE : BLUE
    end

    def display_name(label)
      { "cruby" => "CRuby", "yjit" => "YJIT", "zjit" => "ZJIT",
        "truffleruby" => "TruffleRuby", "jruby" => "JRuby" }.fetch(label,
                                                                      label)
    end

    def log_bounds(values)
      min = [values.min, 1.0].min
      max = [values.max, 1.0].max
      low = 2.0**Math.log2(min).floor
      high = 2.0**Math.log2(max).ceil
      return [low / 2.0, high * 2.0] if low == high

      [low, high]
    end

    def power_ticks(low, high)
      (Math.log2(low).round..Math.log2(high).round).map { |power| 2.0**power }
    end

    def decade_bounds(values)
      low = 10.0**Math.log10(values.min).floor
      high = 10.0**Math.log10(values.max).ceil
      high *= 10 if low == high
      [low, high]
    end

    def decade_ticks(low, high)
      (Math.log10(low).round..Math.log10(high).round).map do |power|
        10.0**power
      end
    end

    def log_position(value, low, high, offset, length)
      offset + (Math.log(value) - Math.log(low)) /
        (Math.log(high) - Math.log(low)) * length
    end

    def format_ratio(value)
      value >= 1 ? format("%.0fx", value) : format("%.2fx", value)
    end

    def format_ms(value)
      value >= 1 ? format("%g", value) : format("%.2g", value)
    end

    def fmt(value)
      format("%.2f", value)
    end

    def escape(value)
      CGI.escapeHTML(value.to_s)
    end
  end
end
