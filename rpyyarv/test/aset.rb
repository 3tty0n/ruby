# ---- every position of an embedded and of a heap array ----

def fill(a)
  i = 0
  while i < a.size
    a[i] = i * 3
    i += 1
  end
  a
end

emb = [0, 0, 0]
heap = Array.new(100, 0)
i = 0
while i < 200
  fill(emb)
  fill(heap)
  i += 1
end
puts emb.inspect
puts heap[0]
puts heap[99]
puts heap.size

# ---- growth past the end still goes to rb_ary_store ----

g = [1, 2, 3]
i = 0
while i < 200
  g[1] = i
  i += 1
end
g[3] = 'grown'
puts g.inspect
g[6] = :far
puts g.inspect
puts g.size

# ---- negative indices, in range and out ----

n = [10, 20, 30, 40]
i = 0
while i < 200
  n[-1] = i
  i += 1
end
puts n.inspect
n[-4] = 'first'
puts n.inspect
begin
  n[-5] = 'nope'
  puts 'no error'
rescue IndexError => e
  puts "IndexError #{e.message.split(';').first}"
end
puts n.inspect

# ---- a frozen array after the fast path is warm ----

fz = [1, 2, 3]
i = 0
while i < 200
  fz[0] = i
  i += 1
end
fz.freeze
begin
  fz[0] = 99
  puts 'no error'
rescue FrozenError
  puts 'FrozenError'
end
puts fz.inspect

# ---- a shared array: the other view must not see the write ----

def poke(a, v)
  i = 0
  while i < 200
    a[0] = v
    i += 1
  end
  a[0]
end

src = (0...100).to_a
view = src[1..]
puts view.first
puts poke(src, 'written')
puts view.first
puts src[0]
puts src[1]

dup = (0...100).to_a
copy = dup.dup
puts poke(copy, :in_copy)
puts dup[0]
puts copy[0]

sliced = (0...100).to_a
tail = sliced[50..]
puts poke(tail, -1)
puts sliced[50]
puts tail[0]
puts tail.size

splat = (0...100).to_a
first = splat[0]
rest = splat[1..]
puts first
puts poke(rest, 'spl')
puts splat[1]
puts rest[0]

# ---- immediates and heap values through the same store ----

mix = [nil, nil, nil, nil]
i = 0
while i < 200
  mix[0] = i
  mix[1] = :sym
  mix[2] = 'string'
  mix[3] = [i]
  i += 1
end
puts mix[0]
puts mix[1].inspect
puts mix[2]
puts mix[3].inspect
mix[0] = nil
mix[1] = true
mix[2] = 1.5
mix[3] = 2**70
puts mix.inspect

# ---- a receiver that is not a plain Array ----

class MyAry < Array
end

class LoggedAry < Array
  def []=(i, v)
    @last = "my:#{v}"
  end

  def last
    @last
  end
end

logged = LoggedAry.new(3, 'x')
logged[0] = 7
puts logged.last
puts logged[0]

sub = MyAry.new(3, 'x')
i = 0
while i < 200
  sub[0] = i
  i += 1
end
puts sub.inspect

h = { 0 => 'a' }
i = 0
while i < 200
  h[0] = i
  i += 1
end
puts h.inspect

s = +'abc'
s[0] = 'Z'
puts s

# ---- an old array repeatedly given fresh young objects ----

old = Array.new(8, nil)
GC.start
GC.start
GC.start
kept = []
i = 0
while i < 60
  old[i % 8] = "young #{i}"
  kept << old[i % 8]
  GC.start if i % 7 == 0
  i += 1
end
GC.start
puts kept.size
puts kept.first
puts kept.last
puts old.inspect

bigold = Array.new(64, 0)
GC.start
GC.start
GC.start
seen = 0
i = 0
while i < 400
  bigold[i % 64] = [i, i + 1]
  seen += bigold[i % 64][1]
  GC.start if i % 97 == 0
  i += 1
end
GC.start
puts seen
puts bigold[0].inspect
puts bigold[63].inspect
puts bigold.map { |p| p[0] }.reduce(:+)
