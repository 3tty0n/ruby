#!/usr/bin/env ruby
# frozen_string_literal: true

# Break each benchmark's peak RSS down from memory.json: host heap as the
# host reports it, framework heap at its peak, JIT machine code, remainder.
#
#   ruby evaluation/membreak.rb RESULTS_DIR/memory.json [--filter NAME ...]
#
# Prints a CSV and, on stderr, the geometric-mean ratios over benchmarks
# every engine completed.

require "json"

path = ARGV.shift or abort "usage: membreak.rb memory.json [--filter NAME]"
filters = []
ARGV.each_slice(2) { |k, v| filters << v if k == "--filter" }
rows = JSON.parse(File.read(path))
mb = ->(b) { b ? (b / 1_048_576.0).round(1) : nil }

by = Hash.new { |h, k| h[k] = {} }
rows.each { |r| by[r["benchmark"]][r["engine"]] = r }

# Startup RSS (an empty script) is the fixed cost of the two runtimes'
# binaries, libraries and initial heaps; the breakdown is of the growth
# above it, which is what a benchmark adds.
startup = by["__startup__"].transform_values { |r| r["peak_rss_bytes"] }
puts %w[benchmark cruby_rss yjit_rss rpyyarv_rss rpyyarv_growth host_heap
        host_memsize framework_peak interp_framework_peak jit_code other
        cruby_host_heap cruby_memsize yjit_code].join(",")
ratios = []
by.each do |bench, eng|
  next if bench == "__startup__"
  next unless filters.empty? || filters.any? { |f| bench.include?(f) }

  c = eng["cruby"]; y = eng["cruby+yjit"]; j = eng["rpyyarv-jit"]
  t = eng["rpyyarv"] || {}
  next unless c && y && j && c["peak_rss_bytes"] && j["peak_rss_bytes"]

  growth = j["peak_rss_bytes"] - startup["rpyyarv-jit"].to_i
  host = j["cruby_heap_pages_bytes"]
  fw = j["rpython_peak_bytes"]
  code = j["jit_code_bytes"]
  other = host && fw && code ? growth - host - fw - code : nil
  puts [bench, mb[c["peak_rss_bytes"]], mb[y["peak_rss_bytes"]],
        mb[j["peak_rss_bytes"]], mb[growth], mb[host],
        mb[j["cruby_memsize_all_bytes"]], mb[fw], mb[t["rpython_peak_bytes"]],
        mb[code], mb[other],
        mb[c["cruby_heap_pages_bytes"]], mb[c["cruby_memsize_all_bytes"]],
        mb[y["cruby_jit_code_bytes"]]].join(",")
  next unless host && fw && code && growth > 0

  ratios << [j["peak_rss_bytes"].to_f / c["peak_rss_bytes"],
             host.to_f / growth, fw.to_f / growth, code.to_f / growth,
             c["cruby_heap_pages_bytes"] ? host.to_f / c["cruby_heap_pages_bytes"] : nil]
end
unless ratios.empty?
  gm = ->(i) { v = ratios.map { |r| r[i] }.compact; Math.exp(v.sum { |x| Math.log([x, 1e-9].max) } / v.size) }
  med = ->(i) { s = ratios.map { |r| r[i] }.compact.sort; s[s.size / 2] }
  warn format("n=%d  rss/cruby gm=%.2f  of growth: host med=%.2f framework med=%.2f code med=%.3f  host heap/cruby host heap gm=%.2f",
              ratios.size, gm[0], med[1], med[2], med[3], gm[4])
end
