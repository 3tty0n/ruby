# ---- every argument shape of Array.new ----

def show(v)
  puts v.inspect
end

show Array.new
show Array.new(0)
show Array.new(3)
show Array.new(3, 7)
show Array.new(3, 'x')

# Array.new(n, obj) shares one object, it does not copy it.
a = Array.new(3, 'x')
a[0] << '!'
show a
show a[0].equal?(a[1])

# ---- the block form ----

show Array.new(4) { |i| i * i }
show Array.new(0) { |i| i }
show(Array.new(3) { 'y' }.map { |s| s.object_id }.uniq.length)

# A block and a second argument: the block wins.
show Array.new(3, 9) { |i| i }

# ---- the copy constructor ----

src = [1, 2, 3]
cp = Array.new(src)
show cp
show cp.equal?(src)
src << 4
show cp

class Aryish
  def to_ary
    [10, 20]
  end
end
show Array.new(Aryish.new)

# ---- a size that is not an Integer ----

class Sized
  def to_int
    5
  end
end
show Array.new(Sized.new)
show Array.new(Sized.new, 1)

# ---- errors ----

begin
  Array.new(-1)
rescue ArgumentError => e
  puts "ArgumentError #{e.message}"
end

begin
  Array.new(-1) { 1 }
rescue ArgumentError => e
  puts "ArgumentError #{e.message}"
end

begin
  Array.new(1 << 62)
rescue ArgumentError, RangeError, NoMemoryError => e
  puts "#{e.class} #{e.message}"
end

begin
  Array.new('nope')
rescue TypeError => e
  puts "TypeError #{e.message}"
end

# ---- a block that raises partway ----

class Boom < StandardError; end

def partial
  Array.new(5) { |i| raise Boom if i == 3; i }
end

begin
  partial
rescue Boom
  puts 'boom'
end

# What the block that raised had already stored, seen through the array itself.
def partial_seen
  out = nil
  begin
    Array.new(5) { |i| out = [] if i == 0; raise Boom if i == 3; out << i; i }
  rescue Boom
  end
  out
end
show partial_seen

# ---- a hot loop, so the JIT sees it ----

def build(n)
  Array.new(n) { |i| i + 1 }
end

sum = 0
i = 0
while i < 2000
  sum += build(4).last
  sum += Array.new(3, 2).length
  sum += Array.new(2).length
  i += 1
end
puts sum

# A bigger one, past the size the in-trace loop takes.
show Array.new(200) { |i| i }.last
show Array.new(200).length

# ---- a subclass receiver must not take the fast path ----

class MyAry < Array
end
m = MyAry.new(3)
show m
show m.class
show MyAry.new(2, :sub)
show(MyAry.new(2) { |i| i })

# ---- Array#initialize redefined ----

class Array
  def initialize(n)
    push(:redefined)
    push(n)
  end
end
show Array.new(3)
show(Array.new(3) { |i| i })
GC.start
show Array.new(4)
