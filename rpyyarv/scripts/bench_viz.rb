#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Read the jsonl history written by bench.rb and emit SVGs. Not part of the worker.

require "json"
require "fileutils"

ROOT = File.dirname(File.dirname(File.expand_path(__FILE__)))
DEFAULT_JSONL = File.join(ROOT, "evaluation", "results", "bench.jsonl")
DEFAULT_OUT = File.join(ROOT, "evaluation", "results", "viz")

require_relative "../evaluation/experiments"
require_relative "../evaluation/plots"

def load_jsonl(path)
  File.readlines(path, chomp: true).filter_map do |line|
    next if line.empty?

    JSON.parse(line)
  end
end

def median_of(value)
  value.is_a?(Hash) ? value["median"] : nil
end

def geomean(values)
  return nil if values.empty?

  Math.exp(values.sum { |v| Math.log(v) } / values.size)
end

def geomean_ratio(raw, den)
  grouped = Hash.new { |h, k| h[k] = {} }
  raw.each do |key, value|
    suite, _bench, engine = key.split("/", 3)
    grouped[[suite, _bench]][engine] = value
  end
  vals = grouped.each_value.filter_map do |engines|
    n = median_of(engines["rpyyarv-jit"])
    d = median_of(engines[den])
    n && d && n.positive? && d.positive? ? n / d : nil
  end
  geomean(vals)
end

def history_svg(records)
  dens = { "yjit" => "cruby+yjit", "cruby" => "cruby", "zjit" => "cruby+zjit" }
  series = dens.each_with_object({}) do |(label, engine), acc|
    points = records.each_with_index.filter_map do |rec, i|
      g = geomean_ratio(rec["raw"] || {}, engine)
      g && [i, g]
    end
    acc[label] = points unless points.empty?
  end
  raise "no ratios in jsonl" if series.empty?

  width = 820
  height = 420
  left = 70
  right = 24
  top = 50
  bottom = 70
  pw = width - left - right
  ph = height - top - bottom
  n = records.size
  ys = series.values.flatten(1).map { |p| p[1] }
  lo, hi = RPyYARVEvaluation::Plotter.log_bounds(ys)
  x = ->(i) { left + i.to_f / [n - 1, 1].max * pw }
  y = ->(v) {
    top + (Math.log2(hi) - Math.log2(v)) / (Math.log2(hi) - Math.log2(lo)) * ph
  }
  p = RPyYARVEvaluation::Plotter
  body = []
  body << p.svg_header(width, height, "Geomean rpyyarv-jit / reference over runs")
  body << p.frame(left, top, pw, ph)
  p.power_ticks(lo, hi).each do |tick|
    yy = y.call(tick)
    body << p.line(left, yy, left + pw, yy, p::GRID, tick == 1 ? 2 : 1)
    body << p.text(left - 8, yy + 4, p.format_ratio(tick), anchor: "end")
  end
  series.each_with_index do |(_label, points), i|
    pts = points.map { |idx, v| "#{p.fmt(x.call(idx))},#{p.fmt(y.call(v))}" }.join(" ")
    body << %(<polyline points="#{pts}" fill="none" stroke="#{p.engine_color(i)}" stroke-width="2"/>)
    points.each do |idx, v|
      body << p.circle(x.call(idx), y.call(v), 3, p.engine_color(i))
    end
  end
  body << p.engine_legend(series.keys, width - 320, 22)
  body << p.axis_title(left + pw / 2, height - 18, "Run (#{records.first["ts"]} .. #{records.last["ts"]})")
  body << p.rotated_axis_title(16, top + ph / 2, "Geomean ratio (log, <1 faster)")
  body << "</svg>\n"
  body.join("\n")
end

def viz(jsonl_path, out_dir)
  abort "no jsonl at #{jsonl_path}" unless File.file?(jsonl_path)

  records = load_jsonl(jsonl_path)
  abort "jsonl is empty" if records.empty?

  FileUtils.mkdir_p(out_dir)
  paths = []
  hist = File.join(out_dir, "history.svg")
  File.write(hist, history_svg(records))
  paths << hist
  last = records.last["raw"] || {}
  unless last.empty?
    begin
      paths.concat(RPyYARVEvaluation::Plotter.plot_raw(last, out_dir))
    rescue StandardError => e
      warn "latest-run plots skipped: #{e.message}"
    end
  end
  paths
end

def main(argv)
  jsonl = argv.shift || DEFAULT_JSONL
  out = argv.shift || DEFAULT_OUT
  viz(jsonl, out).each { |p| puts p }
  0
end

exit(main(ARGV)) if __FILE__ == $PROGRAM_NAME
