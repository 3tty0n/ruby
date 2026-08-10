n = 0
1.send(:times) { n += 1 }
p n

k = 0
[1, 2, 3].send(:each) { |v| k += v }
p k

s = 0
5.__send__(:times) { |i| s += i }
p s

class Counter
  def initialize
    @seen = []
  end

  def each_twice(a)
    yield a
    yield a
    @seen << a
    self
  end

  def seen
    @seen
  end

  def priv_add(x)
    yield x + 1
  end
  private :priv_add
end

c = Counter.new
got = []
c.send(:each_twice, 7) { |v| got << v }
p got
p c.seen

r = 0
c.send(:priv_add, 41) { |v| r = v }
p r

t = []
[10, 20].send(:send, :each) { |v| t << v }
p t

# &blk, where blk is this method's own block parameter
def pass_on(ary, &blk)
  ary.send(:each, &blk)
end
pass_on([1, 2]) { |v| t << v * 2 }
p t

p [3, 1, 2].send(:sort) { |a, b| b <=> a }
p [1, 2, 3].send(:map) { |v| v * 3 }

# break out of a block passed through send
res = [1, 2, 3, 4].send(:each) { |v| break v * 100 if v == 3 }
p res

# a native method that yields, reached through a nested send
p c.send(:__send__, :each_twice, 9) { |v| got << v }.equal?(c)
p got

# send to a method that itself sends with a block
class Runner
  def run(x)
    x.send(:times) { |i| yield i }
  end
end
u = []
Runner.new.run(3) { |i| u << i }
p u

p 3.send("times") { }

# send composed with keyword arguments
class Kw
  def m(a, b: 2, c: 3)
    [a, b, c]
  end

  def rest(a, **kw)
    [a, kw]
  end

  def blk(a, b: 0)
    yield a + b
  end

  def none
    :none
  end
end

kw = Kw.new
p kw.send(:m, 1)
p kw.send(:m, 1, b: 20)
p kw.send(:m, 1, b: 20, c: 30)
p kw.__send__(:m, 1, c: 30)

h = { b: 7, c: 8 }
p kw.send(:m, 1, **h)
p kw.send(:rest, 1, **h)
p kw.send(:rest, 1, x: 9)
p kw.send(:rest, 1, **{})
p kw.send(:send, :m, 1, b: 5)

z = 0
kw.send(:blk, 1, b: 4) { |v| z = v }
p z

p({ a: 1 }.send(:fetch, :a))
p [1, 2, 3].send(:sum, 10)
p kw.send(:none)
