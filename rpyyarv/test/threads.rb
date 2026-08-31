# A second Ruby thread calling RPyYARV methods; CRuby runs their bodies.
class Counter
  def initialize
    @n = 0
  end

  def bump(k)
    @n += k
    ("v" * 8) << k.to_s
    @n
  end

  attr_reader :n
end

$counter = Counter.new
worker = eval('Thread.new { 5_000.times { |i| $counter.bump(i % 7) }; :done }')

main = Counter.new
5_000.times { |i| main.bump(i % 5) }
puts worker.value
puts $counter.n
puts main.n
