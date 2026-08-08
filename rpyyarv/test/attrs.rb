class Point
  attr_reader :x
  attr_writer :y
  attr_accessor :z

  def initialize(a)
    @x = a
    @z = a * 2
  end

  def y_raw
    @y
  end
end

p1 = Point.new(3)
puts p1.x
puts p1.z
p1.z = 40
puts p1.z
p1.y = 7
puts p1.y_raw
puts p1.respond_to?(:x)
puts p1.respond_to?(:y=)
puts Point.instance_methods(false).sort.inspect

# An ivar the constructor never set reads as nil.
class Empty
  attr_accessor :never
end
puts Empty.new.never.inspect

# A def after the generated accessor wins.
class Over
  attr_accessor :v
  def v
    99
  end
end
o = Over.new
o.v = 1
puts o.v

# ... and the generated accessor wins when it comes second.
class Under
  def w
    98
  end
  attr_accessor :w
end
u = Under.new
u.w = 2
puts u.w

# A reopened class gains accessors too.
class Point
  attr_reader :extra
end
p2 = Point.new(1)
puts p2.extra.inspect

# super into an inherited accessor.
class Base
  attr_accessor :b
end
class Derived < Base
  def b
    super
  end

  def b=(v)
    super(v * 10)
  end
end
d = Derived.new
d.b = 5
puts d.b

# Accessors named for the opt_* instructions still route to the ivar.
class Boxy
  attr_accessor :size, :length
end
bx = Boxy.new
bx.size = 11
bx.length = 12
puts bx.size
puts bx.length

# Accessors reached from CRuby's own dispatch.
puts p1.public_send(:x)
puts [p1, p2].map { |q| q.x }.inspect

# String arguments name accessors as well.
class Strung
  attr_accessor 'sv'
end
sv = Strung.new
sv.sv = 'hello'
puts sv.sv

# ---- identity == / != / equal? ----

class Plain
end
a = Plain.new
b = Plain.new
puts a == a
puts a == b
puts a != b
puts a != a
puts a.equal?(a)
puts a.equal?(b)
puts(a == 1)
puts(a == nil)
puts(1 == a)

class OwnEq
  attr_reader :n

  def initialize(n)
    @n = n
  end

  def ==(other)
    other.is_a?(OwnEq) && other.n == @n
  end
end
puts OwnEq.new(1) == OwnEq.new(1)
puts OwnEq.new(1) != OwnEq.new(2)
puts OwnEq.new(1).equal?(OwnEq.new(1))

class Cmp
  include Comparable
  attr_reader :n

  def initialize(n)
    @n = n
  end

  def <=>(other)
    n <=> other.n
  end
end
puts Cmp.new(1) == Cmp.new(1)
puts Cmp.new(1) != Cmp.new(2)
puts Cmp.new(1) < Cmp.new(2)
puts Cmp.new(1).equal?(Cmp.new(1))

# A subclass of a class whose == is identity still is; one below Comparable is not.
class PlainSub < Plain
end
class CmpSub < Cmp
end
puts PlainSub.new == PlainSub.new
ps = PlainSub.new
puts ps == ps
puts CmpSub.new(3) == CmpSub.new(3)

# Immediates and core classes keep value equality.
puts(1 == 1)
puts(1 == 2)
puts(1 != 2)
puts(1000000000000 == 1000000000000)
puts(1.5 == 1.5)
puts(1.5 != 1.5)
puts(1.5.equal?(1.5))
puts('ab' == 'ab')
puts('ab' != 'ab')
puts('ab'.equal?('ab'))
puts(:ab == :ab)
puts(:ab.equal?(:ab))
puts(nil == nil)
puts(nil != nil)
puts(nil.equal?(nil))
puts(true == true)
puts(false == false)
puts(true == false)
puts([1, 2] == [1, 2])
puts([1, 2] != [1, 2])
puts([1, 2].equal?([1, 2]))
puts({ 'a' => 1 } == { 'a' => 1 })

# A == defined after the first comparison must be seen.
class Late
end
l1 = Late.new
l2 = Late.new
puts l1 == l2

class Late
  def ==(_other)
    true
  end
end
puts l1 == l2
puts l1 != l2
puts l1.equal?(l2)
