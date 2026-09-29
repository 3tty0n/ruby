# Singleton classes die while hot loops fold their methods; the GCs that
# find them dead start inside allocations compiled as unable to collect.
class Box
  def initialize(v); @v = v; end
  attr_reader :v
end

def make(i)
  o = Box.new(i)
  if i % 3 == 0
    o.extend(Comparable)
  else
    def o.w; v + 1; end
  end
  o
end

def hot(o, i)
  s = 0
  j = 0
  while j < 50
    s += o.respond_to?(:w) ? o.w : 1
    t = "ab".dup
    t << i.to_s
    s += [t].size + t.size
    j += 1
  end
  s
end

tot = 0
4000.times { |i| tot += hot(make(i), i) }
p tot
