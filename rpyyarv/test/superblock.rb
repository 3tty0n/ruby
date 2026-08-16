# A bare `super` forwards the block its method was given (vm_insnhelper.c:5033),
# whether the method it lands on is RPyYARV's or CRuby's. hexapdf validates a
# document through three such supers before anything yields.

class Base
  def each_one
    yield 1
    yield 2
  end

  def counted
    block_given? ? yield(10) : :none
  end

  def with_args(a, b)
    yield(a + b)
  end
end

class Sub < Base
  def each_one
    super
  end

  def counted
    super
  end

  def with_args(a, b)
    super
  end
end

out = []
Sub.new.each_one { |x| out << x }
p out
p Sub.new.counted { |x| x * 2 }
p Sub.new.counted
p Sub.new.with_args(3, 4) { |v| v * 10 }

# An explicit &blk parameter still leaves a bare super forwarding it.
class Sub2 < Base
  def each_one(&blk)
    super
  end
end
out = []
Sub2.new.each_one { |x| out << x * 3 }
p out

# Two supers deep, and the yield happens inside a block of the super target.
class Deep
  def run
    [1, 2].map { |x| yield x }
  end
end
class Mid < Deep
  def run
    super
  end
end
class Top < Mid
  def run
    super
  end
end
p Top.new.run { |x| x + 100 }

# A lambda as the forwarded block.
double = lambda { |x| x * 2 }
p Sub.new.counted(&double)

# `super` landing on a method CRuby owns, which needs the block just as much.
class Chars < String
  def each_char
    super
  end
end
out = []
Chars.new('abc').each_char { |c| out << c }
p out

# break and a non-local return still cross the forwarded block.
def breaker
  Sub.new.each_one { |x| break :stopped }
end
p breaker

def returner
  Sub.new.each_one { |x| return :returned }
  :not_reached
end
p returner

# The foreign path: a block handed to a CRuby cfunc re-enters here, and a yield
# inside it still finds the method's own block.
def through_cfunc(a)
  out = []
  a.reverse_each { |x| out << yield(x) }
  out
end
p through_cfunc([1, 2]) { |v| v * 10 }
