# Methods RPyYARV defines, reached from CRuby's own dispatch: every core
# method that calls back -- to_s, <=>, ==, hash, inspect, each -- has to find
# the definition RPyYARV holds, not the empty table CRuby was left with.

class Tramp
  def initialize(n)
    @n = n
  end

  def n
    @n
  end

  def to_s
    "Tramp(#{@n})"
  end

  def inspect
    "#<Tramp n=#{@n}>"
  end

  def <=>(other)
    n <=> other.n
  end

  def ==(other)
    other.is_a?(Tramp) && n == other.n
  end

  def eql?(other)
    self == other
  end

  def hash
    @n * 31
  end

  def plain(x)
    x + @n
  end

  def boom
    raise ArgumentError, "boom #{@n}"
  end
end

class Tramp
  include Comparable
end

# to_s through string interpolation and through puts.
t = Tramp.new(3)
puts "interp: #{t}"
puts t
puts t.to_s

# inspect through p and through Array#inspect.
p t
p [t, Tramp.new(4)]

# <=> through Comparable and through sort.
puts(Tramp.new(1) < Tramp.new(2))
puts(Tramp.new(5).between?(Tramp.new(1), Tramp.new(9)))
puts [Tramp.new(3), Tramp.new(1), Tramp.new(2)].sort.map { |x| x.n }.inspect
unsorted = [Tramp.new(3), Tramp.new(1), Tramp.new(2)]
puts unsorted.max.n

# == and hash as a Hash key, and == through Array#include?.
h = {}
h[Tramp.new(2)] = "two"
puts h[Tramp.new(2)].inspect
puts h[Tramp.new(9)].inspect
puts [Tramp.new(1), Tramp.new(2)].include?(Tramp.new(2))

# each driven by a CRuby method: Enumerable calls it with a block of its own.
class Bag
  include Enumerable

  def initialize(items)
    @items = items
  end

  def each
    i = 0
    while i < @items.length
      yield @items[i]
      i = i + 1
    end
    self
  end
end

bag = Bag.new([1, 2, 3])
puts bag.map { |x| x * 10 }.inspect
puts bag.select { |x| x > 1 }.inspect
puts bag.to_a.inspect
puts bag.sort_by { |x| -x }.inspect

# A method RPyYARV defined, called from a file CRuby executed, reached through
# a natively loaded file in between.
require_relative "trampoline_chain"
puts punted_report(t)
puts PuntSub.new.describe

# An exception raised inside an RPyYARV method, caught in Ruby, through both
# an RPyYARV send and a CRuby-driven one.
begin
  t.boom
rescue ArgumentError => e
  puts "rescued: #{e.message}"
end

begin
  [Tramp.new(8)].each { |x| x.boom }
rescue ArgumentError => e
  puts "rescued via each: #{e.message}"
end

# Redefinition after the first call: the CRuby entry must resolve to whatever
# the registry holds now, not to what it held when it was installed.
puts "before: #{t}"

class Tramp
  def to_s
    "REDEFINED(#{@n})"
  end
end

puts "after: #{t}"
puts "after via send: #{t.to_s}"

# Inheritance: the subclass inherits the trampolined entries.
class SubTramp < Tramp
  def to_s
    "Sub(#{@n})"
  end
end

s = SubTramp.new(6)
puts "sub: #{s}"
puts "sub inspect: #{s.inspect}"
puts [SubTramp.new(2), SubTramp.new(1)].sort.map { |x| x.n }.inspect

# The send fast path is untouched: this stays inside RPyYARV.
total = 0
i = 0
while i < 1000
  total = total + t.plain(i)
  i = i + 1
end
puts total
