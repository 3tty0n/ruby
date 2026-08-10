TOP = 'top'

class A
  X = 1
  Y = 'a-y'

  class B
    Z = 3

    def f
      X
    end

    def g
      [X, Y, Z, TOP]
    end
  end

  class Shadow
    Y = 'inner-y'

    def h
      Y
    end
  end

  def outer_x
    X
  end
end

p A::B.new.f
p A::B.new.g
p A::Shadow.new.h
p A.new.outer_x
p A::X
p A::B::Z

module M
  K = 'm-k'

  module N
    def self.k
      K
    end

    class Deep
      def k2
        [K, TOP]
      end
    end
  end
end

p M::N.k
p M::N::Deep.new.k2

class Base
  BASE_C = 'base'

  def base_c
    BASE_C
  end
end

class Derived < Base
  def from_ancestor
    BASE_C
  end
end

p Derived.new.base_c
p Derived.new.from_ancestor
p Derived::BASE_C

# A constant read before it exists raises, and succeeds once defined.
class Late
  def read
    LATER
  end
end

begin
  Late.new.read
  p 'no error'
rescue NameError
  p 'NameError'
end

class Late
  LATER = 'later'
end

p Late.new.read
p Late.new.read

# Nested class method called from outside, and a block inside a method.
class Outer
  W = 10

  class Inner
    def sum
      t = 0
      [1, 2].each { |v| t += v + W }
      t
    end
  end
end

p Outer::Inner.new.sum

# Reopening picks the same lexical scope back up.
class A
  class B
    def again
      [X, Z]
    end
  end
end

p A::B.new.again

# Same-name constant at toplevel and inside; the inner one wins.
DUP_C = 'outer-dup'

class Holder
  DUP_C = 'inner-dup'

  def read
    DUP_C
  end
end

p Holder.new.read
p DUP_C
p ::DUP_C
