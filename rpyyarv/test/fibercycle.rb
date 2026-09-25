# A suspended fiber's frames are traced by its Fiber: a cycle through
# them dies with it, while a held fiber keeps what only its frames hold.

N = 500

def fiber_cycle(wm)
  tag = Object.new
  f = nil
  f = Fiber.new { keep = [f, tag]; Fiber.yield; keep }
  f.resume
  wm[tag] = true
  nil
end

def enum_cycle(wm)
  tag = Object.new
  e = nil
  e = Enumerator.new { |y| keep = [e, tag]; y << 1; y << 2; keep }
  e.next
  wm[tag] = true
  nil
end

%i[fiber_cycle enum_cycle].each do |m|
  wm = ObjectSpace::WeakMap.new
  N.times { send(m, wm) }
  4.times { GC.start }
  puts "#{m} #{wm.keys.size < N / 10}"
end

# Only the suspended frame holds s; a closure writes a young value into it.
setter = nil
held = Fiber.new do
  s = "x" * 40
  setter = proc { |v| s = v }
  Fiber.yield
  s
end
held.resume
4.times { GC.start }
setter.call("y" * 40)
setter = nil
4.times { GC.start(full_mark: false) }
100.times { Array.new(100) { "z" * 40 } }
GC.start
puts held.resume == "y" * 40
