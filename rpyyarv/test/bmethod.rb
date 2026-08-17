# define_method run directly as a method (bmethod), not through the ifunc
# Proc round trip: strict arity, own return/break, definition-site constants.

class Adder
  X = 10
  define_method(:add) { |a, b| a + b }
  define_method(:zero) { 0 }
  define_method(:const) { X }
end

a = Adder.new
puts a.add(1, 2)
puts a.zero
puts a.const

# Strict arity, no autosplat.
begin
  a.add(1)
rescue ArgumentError => e
  puts "few: #{e.class}"
end
begin
  a.add(1, 2, 3)
rescue ArgumentError => e
  puts "many: #{e.class}"
end

# return leaves the method itself, not the block wrapped around it.
class Ret
  define_method(:early) do |n|
    return "early" if n < 0
    [n].each { |x| return "each #{x}" if x == n }
    "late"
  end
end
puts Ret.new.early(-1)
puts Ret.new.early(5)

# break inside the body behaves like a lambda's: it just answers the value,
# matching CRuby's own bmethod (verified against build/ruby).
class Brk
  define_method(:b) { break 42; 0 }
end
puts Brk.new.b

# Defined on a module, included later: the fast entry is looked up through
# the same owner table a `def` in a module uses.
module Greet
  define_method(:hi) { "hi" }
end
class Greeter
  include Greet
end
puts Greeter.new.hi

# Toplevel `main` form lands on Object.
define_method(:toplevel_bm) { "toplevel" }
puts toplevel_bm

# Redefinition is visible on the very next call.
class Redef
  define_method(:v) { 1 }
end
r = Redef.new
puts r.v
class Redef
  define_method(:v) { 2 }
end
puts r.v

# A bmethod called with a block falls back to CRuby's own dispatch instead
# of the fast entry; the call still has to return the right answer.
puts a.add(3, 4) { |x| x }

# The 2-arg (name, method-object) define_method form is never fast-pathed,
# and still has to work.
class TwoArg
  def helper(x)
    x * 3
  end
  define_method(:via_method, instance_method(:helper))
end
puts TwoArg.new.via_method(4)

# define_method with a Proc argument (no literal block) is likewise never
# fast-pathed.
class ProcArg
  add_one = proc { |x| x + 1 }
  define_method(:add_one, &add_one)
end
puts ProcArg.new.add_one(9)
