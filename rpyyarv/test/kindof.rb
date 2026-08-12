module M; end
class A; include M; end
class B < A; end
a = A.new; b = B.new
p a.kind_of?(A)
p a.is_a?(A)
p a.kind_of?(B)
p b.kind_of?(A)
p b.is_a?(M)
p a.kind_of?(M)
p a.kind_of?(Object)
p a.kind_of?(String)
p 1.kind_of?(Integer)
p 1.is_a?(Numeric)
p 1.kind_of?(Comparable)
p nil.is_a?(NilClass)
p :s.kind_of?(Symbol)
p "x".is_a?(Comparable)
p 1.5.kind_of?(Float)
begin
  a.kind_of?(5)
rescue TypeError
  p :TypeError
end
# An include after the first answer must be seen.
class C; end
c = C.new
p c.kind_of?(M)
class C; include M; end
p c.kind_of?(M)

p(:a === :a)
p(:a === :b)
p(:a === "a")
p(Symbol === :a)
sym = :zz
p(sym === :zz)
class Symbol
  def ===(o) = "redefined-eqq"
end
p(:a === :a)
module Kernel
  alias_method :orig_kind_of?, :kind_of?
  def kind_of?(k) = "redefined-kind_of"
end
p 1.kind_of?(Integer)
