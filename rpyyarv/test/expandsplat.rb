# expandarray with the splat (1) and post (2) flags, against vm_expandarray.
a, *b = [1, 2, 3]
p [a, b]

*c, d = [1, 2, 3]
p [c, d]

e, *f = 1
p [e, f]

*g, h = 9
p [g, h]

i, j, *k = [1]
p [i, j, k]

*l, m, n = [1]
p [l, m, n]

o, *mid, q = [1, 2, 3, 4]
p [o, mid, q]

r, *s = []
p [r, s]

*t, u = []
p [t, u]

# A to_ary object expands like the Array it answers.
class ToAry
  def to_ary
    [10, 20, 30]
  end
end

v, *w = ToAry.new
p [v, w]

# A splat expanding past 32 arguments still crosses to CRuby (fileutils
# does public(*METHODS) with 47).
wide = (1..100).to_a
p [].push(*wide).length

module WideMod
  def self.probe(*a)
    a.length
  end
end
p WideMod.probe(*wide)

# In a block's parameters, where net-smtp's capabilities parser uses it.
[[1, 2, 3], [4]].each do |x, *rest|
  p [x, rest]
end
