def target(a, b: 2)
  [a, b]
end
def fwd(...)
  target(...)
end
p fwd(1)
p fwd(1, b: 3)
def helper(x, &b)
  b ? b.call(x) : x
end
def fwd_blk(...)
  helper(...)
end
p(fwd_blk(5) { |v| v * 3 })
p fwd_blk(6)
class SupBase
  def m(a, b: 0)
    [:base, a, b]
  end
end
class SupFwd < SupBase
  def m(...)
    super
  end
end
p SupFwd.new.m(7, b: 8)
def deep(...)
  fwd(...)
end
p deep(9, b: 10)
