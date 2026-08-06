# Megamorphic send: 8 classes round-robin at one call site.

# One call site (o.val) sees 8 receiver class(es) in round-robin order.

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

class C4
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

class C5
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

class C6
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

class C7
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
o4 = C4.new(5)
o5 = C5.new(6)
o6 = C6.new(7)
o7 = C7.new(8)
o0.link(o1)
o1.link(o2)
o2.link(o3)
o3.link(o4)
o4.link(o5)
o5.link(o6)
o6.link(o7)
o7.link(o0)

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
