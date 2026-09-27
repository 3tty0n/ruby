#!/usr/bin/env ruby
# frozen_string_literal: true

# Pearson and Spearman of log(jit/yjit) against log1p of each mechanism
# statistic in DIR/mechanisms.json, with benchmark-bootstrap 95% CIs.
# usage: correlations.rb MECHANISMS-DIR ...   (writes DIR/correlations.csv)

require "json"
require_relative "run"

module Correlations
  PREDICTORS = %w[cruby_sends_per_iteration bridges_per_loop].freeze
  TARGET = "performance_jit_over_yjit"
  RESAMPLES = RPyYARVEvaluation::Bootstrap::RESAMPLES
  SEED = RPyYARVEvaluation::Bootstrap::SEED

  module_function

  def pearson(xs, ys)
    mx = xs.sum / xs.size
    my = ys.sum / ys.size
    sxy = xs.zip(ys).sum { |x, y| (x - mx) * (y - my) }
    sxx = xs.sum { |x| (x - mx)**2 }
    syy = ys.sum { |y| (y - my)**2 }
    sxx.zero? || syy.zero? ? nil : sxy / Math.sqrt(sxx * syy)
  end

  def ranks(values)
    order = values.each_index.sort_by { |i| values[i] }
    result = Array.new(values.size)
    ties = order.chunk_while { |a, b| values[a] == values[b] }
    ties.inject(0) do |start, tie|
      tie.each { |i| result[i] = start + (tie.size - 1) / 2.0 }
      start + tie.size
    end
    result
  end

  def spearman(xs, ys) = pearson(ranks(xs), ranks(ys))

  def points(rows, predictor)
    rows.filter_map do |row|
      x = row[predictor]
      y = row[TARGET]
      next unless x.is_a?(Numeric) && x >= 0 && y.is_a?(Numeric) && y.positive?

      [Math.log1p(x), Math.log(y)]
    end
  end

  def ci(pts, method)
    rng = Random.new(SEED)
    stats = Array.new(RESAMPLES) do
      sample = Array.new(pts.size) { pts[rng.rand(pts.size)] }
      send(method, sample.map(&:first), sample.map(&:last))
    end.compact.sort
    [0.025, 0.975].map { |q| stats[(q * (stats.size - 1)).round] }
  end

  def analyze(rows)
    PREDICTORS.flat_map do |predictor|
      pts = points(rows, predictor)
      %i[pearson spearman].map do |method|
        lo, hi = ci(pts, method)
        { "predictor" => predictor, "method" => method.to_s, "n" => pts.size,
          "r" => send(method, pts.map(&:first), pts.map(&:last)),
          "ci_lo" => lo, "ci_hi" => hi }
      end
    end
  end

  def main(dirs)
    abort "usage: correlations.rb MECHANISMS-DIR ..." if dirs.empty?
    dirs.each do |dir|
      rows = analyze(JSON.parse(File.read(File.join(dir, "mechanisms.json"))))
      RPyYARVEvaluation::Csv.write(File.join(dir, "correlations.csv"),
                                   %w[predictor method n r ci_lo ci_hi], rows)
      rows.each do |row|
        puts format("%-26s %-8s n=%d r=%.3f [%.3f, %.3f]  %s", row["predictor"],
                    row["method"], row["n"], row["r"], row["ci_lo"],
                    row["ci_hi"], File.basename(dir))
      end
    end
    0
  end
end

exit Correlations.main(ARGV) if $PROGRAM_NAME == __FILE__
