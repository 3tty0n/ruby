# A Proc RPyYARV made dies and CRuby reuses its address; the next Proc at
# that address must resolve to its own block, never to the dead one's.

def call_it(&b)
  b.call
end

def run_it(b)
  b.call
end

def mk(v)
  lambda { |*| v }
end

bad = 0
20_000.times do |i|
  p = mk(i)
  bad += 1 unless call_it(&p) == i
  bad += 1 unless run_it(p) == i
  bad += 1 unless [1].map(&p).first == i
  p = nil
  GC.start if i % 500 == 0
end
puts bad

# The same for a block a method captured and handed on.
def keep(&b)
  b
end

seen = []
5_000.times do |i|
  b = keep { i * 2 }
  seen << call_it(&b)
  GC.start if i % 250 == 0
end
puts seen == (0...5_000).map { |i| i * 2 }
