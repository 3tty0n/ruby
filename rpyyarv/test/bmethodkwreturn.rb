# `return` leaves a bmethod CRuby owns: define_method bodies whose parameters
# RPyYARV does not register are still the method body, not a plain block.
class C
  define_method(:kw) do |x, **o|
    return :early if x
    :late
  end
  define_method(:opt) do |x, y = 1|
    [1].each { return [:early, y] if x }
    [:late, y]
  end
end
c = C.new
p [c.kw(true), c.kw(false, a: 1)]
p [c.opt(true), c.opt(false, 2)]
p c.public_send(:kw, true)
p [1, 2].map { |n| c.kw(n == 1) }
