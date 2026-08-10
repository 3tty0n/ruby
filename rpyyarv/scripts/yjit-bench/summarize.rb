# Median-of-3-processes steady-state table from timings.tsv.
S = File.dirname(File.expand_path(__FILE__))
rows = Hash.new { |h, k| h[k] = Hash.new { |g, j| g[j] = [] } }
order = []
File.readlines("#{S}/timings.tsv").each do |line|
  name, eng, _p, med = line.chomp.split("\t")
  order << name unless order.include?(name)
  rows[name][eng] << med
end

def med(a)
  nums = a.grep(/\A[\d.]+\z/).map(&:to_f).sort
  return nil if nums.empty?
  nums.length.odd? ? nums[nums.length / 2] : (nums[nums.length / 2 - 1] + nums[nums.length / 2]) / 2
end

engines = %w[rpyyarv-jit rpyyarv cruby yjit]
puts format("%-22s %11s %11s %11s %11s %9s %9s", "benchmark", *engines, "jit/cruby", "jit/yjit")
order.each do |name|
  vals = engines.map { |e| med(rows[name][e]) }
  cells = engines.each_with_index.map { |e, i| vals[i] ? format("%11.1f", vals[i]) : format("%11s", rows[name][e].first || "-") }
  r1 = vals[0] && vals[2] ? format("%9.2f", vals[0] / vals[2]) : format("%9s", "-")
  r2 = vals[0] && vals[3] ? format("%9.2f", vals[0] / vals[3]) : format("%9s", "-")
  puts format("%-22s %s %s%s", name, cells.join(" "), r1, r2)
end
