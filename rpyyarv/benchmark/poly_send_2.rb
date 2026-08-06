# Polymorphic send: 2 classes alternating at one call site.

# One call site (o.val) sees 2 receiver class(es) in round-robin order.

class C0
  def initialize(v)
    @v = v
    @nxt = 0
  end
  def val
    @v
  end
  def nxt
    @nxt
  end
  def link(o)
    @nxt = o
    0
  end
end

class C1
  def initialize(v)
    @v = v
    @nxt = 0
  end
  def val
    @v
  end
  def nxt
    @nxt
  end
  def link(o)
    @nxt = o
    0
  end
end


o0 = C0.new(1)
o1 = C1.new(2)
o0.link(o1)
o1.link(o0)

n = 20000000
i = 0
s = 0
o = o0
while i < n
  s = s + o.val
  o = o.nxt
  i = i + 1
end
puts s
