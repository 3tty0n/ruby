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
  rescue StandardError => e
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

# An explicit Hash argument stays a positional; only ** makes it keywords.
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

# ** at a call site: the keywords arrive as one Hash, matched by name here.
h = { a: 1, b: 2 }
p opt(**h)
p opt(**{ b: 9 })
p opt(**{})
p req(**h)
p rest(**{ a: 1, c: 3 })
p only_rest(**h)
p mixed(1, 2, **{ a: 30 })
p takes_hash(**h)
p Point.new(**{ x: 7, y: 8 }).to_a

def forward(**o)
  opt(**o)
end

p forward
p forward(a: 4)
p forward(**h)

# Literal keywords beside a **: the compiler merges them into one Hash first.
p opt(a: 5, **{ b: 6 })
p opt(**h, b: 7)
p rest(a: 1, **{ c: 3 })

# A Hash with a key no parameter declares, and one with none missing.
show('splat unknown') { opt(**{ c: 1 }) }
show('splat missing') { req(**{ a: 1 }) }
p rest(**{ a: 1, 'str' => 2 })

# A ** of something that is not a Hash goes through to_hash first.
class Hashish
  def to_hash
    { a: 5 }
  end
end

class HashSub < Hash
end

p opt(**Hashish.new)
show('not a hash') { opt(**1) }
sub = HashSub.new
sub[:a] = 9
p opt(**sub)
p opt(**Hash.new(0))

# Foreign: the Hash has to reach CRuby flagged as keywords.
p P.new(**{ x: 3, y: 4 }).sum

# Keywords to super, both literal and splatted.
class Base
  def go(a: 1, b: 2)
    [a, b]
  end
end

class Sub < Base
  def go(a: 1, b: 2)
    super(a: a + 1, b: b)
  end
end

class Sub2 < Base
  def go(**o)
    super(**o)
  end
end

class Sub3 < Base
  def go(a: 1, b: 2)
    super
  end
end

p Sub.new.go
p Sub.new.go(a: 5, b: 6)
p Sub2.new.go(a: 3, b: 4)
p Sub3.new.go(a: 8)

# Keywords to yield.
def yielder
  yield(a: 9)
end

p(yielder { |a: 0, b: 1| [a, b] })
p(yielder { |h| h })

def yield_splat(h)
  yield(**h)
end

p(yield_splat(h) { |a: 0, b: 0| [a, b] })
p(yield_splat({}) { |a: 7| a })

# A block reached through Proc#call, and a block with a **rest.
def as_proc(&b)
  b
end

blk = as_proc { |a:, **o| [a, o] }
p blk.call(a: 1, z: 2)
p blk.call(**{ a: 3, y: 4 })
p(yield_splat({ a: 1, q: 2 }) { |a:, **o| [a, o] })

total = 0
i = 0
while i < 2000
  total += req(a: i, b: 1)
  total += opt(a: i)[0]
  total += mixed(i, 1, a: 2)[3]
  total += opt(**{ a: i })[0]
  total += Sub.new.go(a: i)[0]
  i += 1
end
p total
