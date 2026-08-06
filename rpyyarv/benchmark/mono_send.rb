# Monomorphic send: hot loop calling x.val on one class.

# One call site (o.val) sees 1 receiver class(es) in round-robin order.

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


o0 = C0.new(1)
o0.link(o0)

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
