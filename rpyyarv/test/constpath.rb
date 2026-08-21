# Qualified A::B is rb_public_const_get_from: a name that only Object holds
# is not a hit, and a private constant is not either.

TOPLEVEL_ONLY = 1

class Q; end
module R; end

begin
  Q::TOPLEVEL_ONLY
rescue NameError => e
  puts e.class
end
begin
  R::TOPLEVEL_ONLY
rescue NameError => e
  puts e.class
end

# ::Foo still resolves: rb_const_search clears exclude for Object itself.
puts ::TOPLEVEL_ONLY
puts Object::TOPLEVEL_ONLY

class S
  INSIDE = 2
  def self.read = INSIDE
end
puts S::INSIDE
puts S.read

class T < S; end
puts T::INSIDE

module U
  IN_U = 3
end
class V; include U; end
puts V::IN_U

# private_constant is not enforced here: rb_public_const_get_from is not
# exported, so the shim uses rb_const_get_from (same exclude, no visibility).
class W
  HIDDEN = 4
  def self.read = HIDDEN
end
puts W.read

# A non-namespace on the left is a TypeError.
begin
  eval("1::Foo")
rescue TypeError => e
  puts e.class
end

# Nested paths keep working.
module X
  module Y
    Z = 5
  end
end
puts X::Y::Z
puts ::X::Y::Z

# const_missing still runs for a real miss.
class N
  def self.const_missing(name) = "missing #{name}"
end
puts N::NOPE

# defined? on a qualified path follows the same rule as the lookup.
p defined?(Q::TOPLEVEL_ONLY)
p defined?(R::TOPLEVEL_ONLY)
p defined?(::TOPLEVEL_ONLY)
p defined?(Object::TOPLEVEL_ONLY)
p defined?(S::INSIDE)
p defined?(T::INSIDE)
p defined?(V::IN_U)
p defined?(X::Y::Z)
p defined?(X::Y::NOPE)
