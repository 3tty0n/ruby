def all(*a) = a
def two(x, y) = [x, y]
def opt(a, b = 5, *r, c) = [a, b, r, c]
def kw(a, k: 1) = [a, k]

b = [1, 2]

p all(*b)
p all(0, *b)
p all(*b, 9)
p all(1, *b, 9)
p all(*[])
p all(0, *[])
p two(*b)
p opt(*[1, 2, 3, 4, 5])
p kw(*[7], k: 8)
p kw(*[7], **{ k: 9 })
p all(*b, **{})
# A *splat is to_a, not to_ary: a Range spreads, a String does not.
p all(*(1..4))
p [*0..4].size
p all(*"str")

def blk(*a)
  yield(*a)
end
p blk(*b) { |x, y| x + y }

# The splat Array must not be handed to the callee's *rest by reference.
src = [1, 2]
got = all(*src)
got << 3
p src

# A foreign (CRuby) method reached with a splat.
p [3, 1, 2].sort_by { |v| v }
p "a-b-c".split(*["-"])
p [1, 2, 3].push(*b)

o = Object.new
def o.m(*a) = ["m", a]
p o.send(*[:m, 1, 2])
p o.send(*[:m])
name = "m"
p o.send(*[name, 5])

# send with a splat that is not a pristine send.
p 3.send(*[:+, 4])

# yield through a splat, and a block with a splat call site.
p [[1, 2], [3, 4]].map { |x, y| two(*[x, y]) }

class A
  def initialize(*a)
    @a = a
  end
  def to_a = @a
end
p A.new(*b).to_a
p A.new(*b, 9).to_a
