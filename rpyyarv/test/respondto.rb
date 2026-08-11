class A
  def pub; end
  def prot; end
  protected :prot
  def priv; end
  private :priv
end

class B < A
end

a = A.new
b = B.new

puts a.respond_to?(:pub)
puts a.respond_to?(:prot)
puts a.respond_to?(:priv)
puts a.respond_to?(:nope)
puts a.respond_to?(:priv, true)
puts a.respond_to?("pub")
puts b.respond_to?(:pub)
puts b.respond_to?(:nope)
puts 1.respond_to?(:+)
puts nil.respond_to?(:to_a)
puts :sym.respond_to?(:to_proc)

# The cache must survive a definition on the class it answered for.
n = 0
3.times { n += 1 if b.respond_to?(:added) }
class A
  def added; end
end
3.times { n += 1 if b.respond_to?(:added) }
puts n

# ... and an undef, and a module included after the fact.
class A
  undef_method :added
end
puts b.respond_to?(:added)

module Extra
  def from_module; end
end
puts b.respond_to?(:from_module)
class B
  include Extra
end
puts b.respond_to?(:from_module)

# A singleton method belongs to that object alone.
o1 = A.new
o2 = A.new
def o1.only_mine; end
puts o1.respond_to?(:only_mine)
puts o2.respond_to?(:only_mine)

# respond_to_missing? answers per receiver, so no per-class answer exists.
class Ghost
  def initialize(yes) = @yes = yes
  # No `super`: reaching CRuby's Kernel#respond_to_missing? from here is a separate gap.
  def respond_to_missing?(name, include_private = false)
    name == :ghost && @yes
  end
end
g1 = Ghost.new(true)
g2 = Ghost.new(false)
puts g1.respond_to?(:ghost)
puts g2.respond_to?(:ghost)
puts g1.respond_to?(:nothing)

# An overridden respond_to? wins outright.
class Liar
  def respond_to?(*_args) = true
end
puts Liar.new.respond_to?(:anything)
