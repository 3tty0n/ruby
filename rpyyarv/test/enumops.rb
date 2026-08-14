# Prelude collection methods and the dispatch paths they lean on.

p [1, 2, 3].inject(:+)
p [1, 2, 3].inject(10) { |a, v| a + v }
p [1, 2, 3].inject(2, :*)
p [].inject { |a, v| a + v }
p({ a: 1, b: 2 }.inject(0) { |a, (_k, v)| a + v })
p [1, 2, 3].reduce(:+)

class Walker
  include Enumerable
  def each
    yield 1, :x
    yield 2, :y
  end
end
p Walker.new.inject([]) { |a, (n, s)| a << [s, n] }

p [1, 2, 3].first
p [].first
p [1, 2, 3].first(2)
p [1, 2, 3].last
p [].last
p [1, 2, 3].last(2)
p [1, 2, 3].last(9)
p [].empty?
p [1].empty?
p [1, 2, 3].include?(2)
p [1, 2, 3].include?(9)
p [1, :a, 1, nil].count
p [1, :a, 1, nil].count(1)
p [1, 2, 3, 4].count(&:even?)
p [nil, false].any?
p [nil, 3].any?
p [1, 2].any? { |v| v > 1 }
p [1, 2].any?(Integer)
p [1, 2].all?
p [1, nil].all?
p [2, 4].all? { |v| v.even? }
p [2, 4].all?(Integer)

h = { "k" => 1, :s => nil }
p h.fetch("k")
p h.fetch(:s)
p h.fetch(:missing, 9)
p h.fetch(:missing) { |k| [k, 7] }
d = Hash.new { |_h, _k| :default }
d[:present] = 5
p d.fetch(:present)
p d.fetch(:absent, :arg)
begin
  h.fetch(:nope)
rescue KeyError => e
  p [e.class, e.key, e.receiver.equal?(h)]
end

g = { a: 1, b: 2 }
acc = []
r = g.each { |k, v| acc << [k, v] }
p acc
p r.equal?(g)
g.each { |*e| acc << e }
p acc[2]
p g.each_pair { |k, v| }.equal?(g)
ka = []
p g.each_key { |k| ka << k }.equal?(g)
p ka
p(g.select { |k, v| v > 1 })
p(g.select { |*e| e == [:a, 1] })
p g.filter { |_k, v| v.odd? }
m = { a: 1, b: 2 }
p m.merge!({ b: 3, c: 4 }) { |k, o, n| [k, o, n] }
p m.merge!({ d: 9 })
p m.update({ a: 0 }).equal?(m)
p({ a: 1, b: 2 }.map { |k, v| [v, k] })
p({ a: 1 }.map { |*e| e })
p((1..4).map { |v| v * 2 })
p((1..4).collect { |v| v + 1 })
p({ a: 2, b: 3 }.find { |_k, v| v == 3 })
p [1, 2, 3].find { |v| v > 1 }
p [1, 2, 3].detect { |v| v > 9 }
p({ x: 5 }.each_with_object([]) { |(k, v), o| o << [k, v] }) rescue p :no_ewo

p 4.even?
p 5.even?
p(-3.even?)
p 5.odd?
p(-4.odd?)

p 5.tap { |v| p v * 2 }

p(1 == nil)
p(1 != nil)
p(0 != nil)

module NamedPart
  def part_name = "from module"
end
class Object
  def part_name = "from object"
end
class String
  include NamedPart
end
p "x".part_name
p 1.part_name

class Helpers
  class << self
    def real(x) = x * 3
    alias_method :shortcut, :real
  end
end
p Helpers.shortcut(4)
p Helpers.respond_to?(:shortcut)

class Pair
  attr_accessor :left
  alias_method :first_of, :left
end
q = Pair.new
q.left = 8
p q.first_of
