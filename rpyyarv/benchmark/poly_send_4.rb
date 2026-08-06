# Polymorphic send: 4 classes round-robin; probes bridge growth.

# One call site (o.val) sees 4 receiver class(es) in round-robin order.

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

class C2
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

class C3
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
o2 = C2.new(3)
o3 = C3.new(4)
o0.link(o1)
o1.link(o2)
o2.link(o3)
o3.link(o0)

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
