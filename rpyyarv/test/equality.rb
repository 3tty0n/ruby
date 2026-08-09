# The == cases the fast paths answer without calling CRuby, and the ones they
# must hand back.
a = [1, 2]
empty = []
p a == nil
p empty == nil
p empty == false
p empty == 0
p empty == :sym
p a != nil
p a == a
p a == [1, 2]
p a == [1, 3]
p a == "x"
p nil == nil
p nil == a
p nil == false
p 1 == 1.0
p 1.0 == 1
p 1 == 2
p :a == :a
p :a == "a"
p "a" == :a
p "a" == "a"
p 1 == nil
p nil == 1

class EqBox
  def initialize(n); @n = n; end
end
b1 = EqBox.new(1)
b2 = EqBox.new(1)
p b1 == b1
p b1 == b2
p b1 == nil
p b1 != nil

# An argument that answers to_ary is compared the other way round, so the
# immediate shortcut must not fire for it.
class Coercible
  def to_ary; [1, 2]; end
end
p a == Coercible.new
p a == 7

# Last: an immediate that grows a to_ary is compared the other way round too,
# so the shortcut has to notice the definition that was not there before.
class Symbol
  def to_ary; [1, 2]; end
  def ==(other); true; end
end
p a == :x
