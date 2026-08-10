def req(a:, b:)
  a - b
end

def opt(a: 1, b: 2)
  [a, b]
end

def mixed(x, y = 10, a: 3, b: x + y)
  [x, y, a, b]
end

def rest(a:, **o)
  [a, o]
end

def only_rest(**o)
  o
end

def takes_hash(h)
  h
end

def with_block(a:, b: 2)
  yield(a + b)
end

class Point
  def initialize(x:, y: 0)
    @x = x
    @y = y
  end

  def to_a
    [@x, @y]
  end
end

def show(label)
  begin
    p yield
  rescue ArgumentError => e
    puts "#{label}: #{e.message}"
  end
end

p req(a: 10, b: 3)
p req(b: 3, a: 10)
p opt
p opt(b: 9)
p opt(a: 8, b: 9)
p mixed(1)
p mixed(1, 2)
p mixed(1, 2, a: 30)
p mixed(1, 2, b: 40)
p rest(a: 1)
p rest(a: 1, c: 3, d: 4)
p only_rest
p only_rest(z: 1)
p takes_hash(k: 1, j: 2)
p with_block(a: 5) { |v| v * 100 }
p Point.new(x: 7).to_a
p Point.new(x: 7, y: 8).to_a

show('missing one') { req(a: 1) }
show('missing two') { req }
show('unknown') { opt(c: 1) }
show('unknown two') { opt(c: 1, d: 2) }

# A hash literal reaches a keyword parameter only through **, which is punted;
# an explicit Hash argument still has to stay a positional.
p takes_hash({ a: 1 })

# Defaults that read earlier parameters and earlier keywords.
def chained(a: 1, b: a + 1, c: b + 1)
  [a, b, c]
end

p chained
p chained(a: 10)
p chained(b: 20)
p chained(a: 1, b: 2, c: 3)

# A keyword-taking method reached through a block's frame.
def outer(n)
  [1, 2, n].map { |i| opt(a: i) }
end

p outer(5)

# Foreign: a CRuby method taking keywords and a block at once.
P = Struct.new(:x, :y, keyword_init: true) do
  def sum
    x + y
  end
end

p P.new(x: 1, y: 2).sum

# Foreign: a CRuby method that takes keywords.
p [3, 1, 2].sum
p "a-b-c".split("-")
p Hash[[[1, 2]]]
p 1.0.round(1)
p [1, 2, 3].each_slice(2).to_a

total = 0
i = 0
while i < 2000
  total += req(a: i, b: 1)
  total += opt(a: i)[0]
  total += mixed(i, 1, a: 2)[3]
  i += 1
end
p total
