# A fiber suspends without unwinding, so every switch saves and restores the
# shadowstack and the frame chain the suspended block still needs.

def collect(n)
  a = []
  n.times { |i| a << "garbage #{i}" }
  a.size
end

# Values across resume/yield, and several yields from one block.
f = Fiber.new do |first|
  second = Fiber.yield(first * 2)
  third = Fiber.yield(second + 1)
  "done #{third}"
end
p f.resume(3)
p f.resume(10)
p f.resume(:last)
p f.alive?

# Frames of ours nested inside the fiber, each with locals to keep marked.
def deep(n, &blk)
  return blk.call(n) if n.zero?
  deep(n - 1, &blk) + n
end

g = Fiber.new do
  deep(4) { |n| Fiber.yield("at #{n}"); 100 }
end
p g.resume
p g.resume

# Two fibers interleaved, so a switch is not always to the resumer.
a = Fiber.new { 3.times { |i| Fiber.yield("a#{i}") }; 'a done' }
b = Fiber.new { 3.times { |i| Fiber.yield("b#{i * 2}") }; 'b done' }
8.times { |i| print(i.even? ? a.resume : b.resume, ' ') }
puts

# A collection while a fiber sits suspended, with its own frames live.
h = Fiber.new do
  words = %w[one two three]
  Fiber.yield(words.join('-'))
  words.map { |w| w.upcase }.join(',')
end
p h.resume
p collect(200)
GC.start
p h.resume

# Never resumed to completion, then dropped and collected.
2.times do
  lost = Fiber.new { Fiber.yield(:parked); :never }
  p lost.resume
end
p collect(200)
GC.start
p :survived

# A subclass carrying state of its own, hexapdf's FiberWithLength shape.
class FiberWithLength < Fiber
  attr_reader :length

  def initialize(length)
    @length = length
    super()
  end
end

fw = FiberWithLength.new(7) { |x| Fiber.yield(x + 1); :end }
p fw.length
p fw.resume(1)
p fw.resume
p Class.new(Fiber).new { :anon }.resume

# An exception out of the block, at the resume that raised it.
bad = Fiber.new { raise ArgumentError, 'from inside' }
begin
  bad.resume
rescue ArgumentError => e
  p [e.class, e.message]
end
p bad.alive?

# Raised past a yield: the fiber is resumed once, then blows up.
late = Fiber.new { Fiber.yield(:ok); raise 'later' }
p late.resume
begin
  late.resume
rescue RuntimeError => e
  p e.message
end

# kill: ensure runs, the fiber is dead, and no rescue in it may see the kill.
k = Fiber.new do
  begin
    Fiber.yield(:before)
    :unreached
  rescue Exception => e
    puts "rescued #{e.class}"
  ensure
    puts 'ensured'
  end
end
p k.resume
p k.kill.equal?(k)
p k.alive?
begin
  k.resume
rescue FiberError => e
  p e.class
end

# A loop hot enough to compile, suspended in the middle of it.
counter = Fiber.new do
  total = 0
  1000.times do |i|
    total += i
    Fiber.yield(total) if (i % 250).zero?
  end
  total
end
p Array.new(5) { counter.resume }

# One fiber resuming another, so the switch is not always back to the resumer.
outer = Fiber.new do
  inner = Fiber.new { Fiber.yield(:inner1); :inner2 }
  Fiber.yield(inner.resume)
  inner.resume
end
p outer.resume
p outer.resume

p collect(200)
GC.start
p :end
