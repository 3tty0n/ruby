# ---- immediate and heap values through the same writer ----

class Box
  attr_accessor :a, :b

  def initialize
    @a = 0
    @b = nil
  end

  def bump(n)
    @a = n
  end

  def hold(o)
    @b = o
  end
end

bx = Box.new
i = 0
while i < 200
  bx.bump(i)
  i += 1
end
puts bx.a
bx.bump(:sym)
puts bx.a.inspect
bx.bump(nil)
puts bx.a.inspect
bx.bump(true)
puts bx.a.inspect
bx.bump(1.5)
puts bx.a.inspect
bx.bump(2**70)
puts bx.a.inspect
bx.hold('a string')
puts bx.b
bx.hold([1, 2, 3])
puts bx.b.inspect
bx.a = 7
puts bx.a
bx.b = 'via writer'
puts bx.b

# ---- a frozen receiver still raises ----

fr = Box.new
i = 0
while i < 200
  fr.bump(i)
  i += 1
end
fr.freeze
puts fr.frozen?
begin
  fr.bump(1)
  puts 'no error'
rescue FrozenError => e
  puts "FrozenError #{e.message.split(':').first}"
end
begin
  fr.a = 2
  puts 'no error'
rescue FrozenError => e
  puts 'FrozenError from writer'
end
puts fr.a
puts fr.b.inspect

# ---- a new ivar after the fast path is warm forces a shape transition ----

class Grow
  def initialize
    @x = 0
  end

  def set_x(v)
    @x = v
  end

  def add_y(v)
    @y = v
  end

  def add_z(v)
    @z = v
  end

  def dump
    [@x, @y, @z]
  end
end

g = Grow.new
i = 0
while i < 200
  g.set_x(i)
  i += 1
end
puts g.dump.inspect
g.add_y(5)
puts g.dump.inspect
g.add_z('zed')
puts g.dump.inspect
i = 0
while i < 200
  g.set_x(i * 2)
  i += 1
end
puts g.dump.inspect

# Many instances, each transitioning at a different point.
objs = []
i = 0
while i < 50
  o = Grow.new
  o.set_x(i)
  o.add_y(i + 1) if i.even?
  o.add_z(i + 2) if i % 3 == 0
  objs << o
  i += 1
end
sum = 0
objs.each { |o| sum += o.dump.compact.size }
puts sum

# ---- generational barrier: an old object written with a young value ----

class Node
  attr_accessor :child, :n

  def initialize
    @child = nil
    @n = 0
  end
end

old = Node.new
GC.start
GC.start
GC.start
kept = []
i = 0
while i < 40
  fresh = Node.new
  fresh.n = i
  old.child = fresh
  kept << old.child
  old.n = i
  GC.start if i % 7 == 0
  i += 1
end
GC.start
puts kept.size
puts kept.map { |k| k.n }.inspect
puts old.child.n
puts old.n

# A long-lived object repeatedly given young strings, with majors in between.
holder = Node.new
GC.start
seen = []
i = 0
while i < 30
  holder.child = "young #{i}"
  seen << holder.child
  GC.start if i % 5 == 0
  i += 1
end
GC.start
puts seen.size
puts seen.first
puts seen.last
puts holder.child

# ---- a too-complex object falls back ----

class Complex1
  def initialize(order)
    order.each { |k| instance_variable_set("@iv#{k}", k) }
  end

  def get(k)
    instance_variable_get("@iv#{k}")
  end

  def bump_first
    @iv0 = (@iv0 || 0) + 1
  end
end

# Enough distinct transition orders on one class to blow the shape variation
# limit, which is what pushes an object's ivars into a hash table.
cs = []
i = 0
while i < 24
  cs << Complex1.new((0..11).to_a.rotate(i))
  i += 1
end
puts cs.size
puts cs.map { |c| c.get(3) }.uniq.inspect
last = cs.last
i = 0
while i < 100
  last.bump_first
  i += 1
end
puts last.get(0)
puts cs.first.get(0)

# ---- a constructor run often enough for the transitions to be warm ----

class Point4
  attr_reader :x, :y, :z, :w

  def initialize(i)
    @x = i
    @y = i + 1
    @z = "s#{i % 3}"
    @w = nil
  end

  def sum
    @x + @y
  end
end

total = 0
tags = {}
i = 0
while i < 3000
  p = Point4.new(i)
  total += p.sum
  tags[p.z] = true
  i += 1
end
puts total
puts tags.keys.sort.inspect
last = Point4.new(7)
puts [last.x, last.y, last.z, last.w].inspect

# Same ivar names, a second class: the shape edges already exist.
class Point4b
  def initialize(i)
    @x = i
    @y = i * 2
  end

  def pair
    [@x, @y]
  end
end

acc = 0
i = 0
while i < 3000
  acc += Point4b.new(i).pair.last
  i += 1
end
puts acc

# Two orders on one class, so the shape tree branches under the same parent.
class Either
  def initialize(flip)
    if flip
      @p = 1
      @q = 2
    else
      @q = 3
      @p = 4
    end
  end

  def both
    [@p, @q]
  end
end

sums = [0, 0]
i = 0
while i < 2000
  b = Either.new(i.even?).both
  sums[0] += b[0]
  sums[1] += b[1]
  i += 1
end
puts sums.inspect

# An extra ivar appears only after the two-ivar transition is warm.
class Late
  def initialize(i)
    @a = i
    @b = i + 1
    @c = i + 2 if i >= 2500
  end

  def dump
    [@a, @b, @c]
  end
end

lates = []
i = 0
while i < 3000
  o = Late.new(i)
  lates << o if i % 1000 == 0 || i == 2999
  i += 1
end
puts lates.map { |o| o.dump }.inspect

# A frozen instance of a class whose transitions are warm.
frozen = Point4.new(1)
frozen.freeze
begin
  frozen.instance_variable_set(:@fresh, 1)
  puts 'no error'
rescue FrozenError
  puts 'FrozenError on transition'
end
puts frozen.x

# ---- ivars on things that are not plain objects ----

s = 'str'
s.instance_variable_set(:@tag, 1)
puts s.instance_variable_get(:@tag)
ary = [1]
ary.instance_variable_set(:@tag, :two)
puts ary.instance_variable_get(:@tag).inspect
puts Box.new.instance_variable_get(:@nope).inspect
