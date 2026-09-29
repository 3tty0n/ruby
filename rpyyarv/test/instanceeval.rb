class Box
  def initialize(n)
    @n = n
  end
  def secret = "box#{@n}"
  SCOPED = "in-box"
end

b = Box.new(1)
puts b.instance_eval { self.class }
puts b.instance_eval { secret }
puts b.instance_eval { @n }
puts b.instance_eval { |o| o.equal?(b) }
begin
  b.instance_eval { SCOPED }
rescue NameError
  puts "NameError SCOPED"
end
puts b.instance_exec(2, 3) { |x, y| secret + (x + y).to_s }
puts b.instance_exec { @n }

# A DSL: the block's receiver decides what the bare calls mean.
class Builder
  def initialize = @parts = []
  def use(x) = @parts << x
  def run(&blk)
    instance_eval(&blk)
    @parts.join(",")
  end
end
puts Builder.new.run { use "a"; use "b" }

# `def` inside instance_eval defines a singleton method.
o = Box.new(9)
o.instance_eval do
  def only_here = "singleton"
end
puts o.only_here
puts Box.new(9).respond_to?(:only_here)

# Locals of the enclosing scope stay visible.
outer = "captured"
puts b.instance_eval { outer }

# The block's own self is restored afterwards.
puts self.to_s
puts b.instance_eval { 1 }
puts self.to_s

# Nested, and on a class object.
puts Box.instance_eval { name }
puts b.instance_eval { Box.new(5).instance_eval { @n } }

# Returning and raising out of the block.
def wrapper(b)
  b.instance_eval { return "early" }
  "late"
end
puts wrapper(b)
begin
  b.instance_eval { raise "boom" }
rescue RuntimeError => e
  puts e.message
end

# An immediate receiver has no singleton class, but self still rebinds.
puts 7.instance_eval { self + 1 }
puts nil.instance_eval { inspect }
puts :s.instance_exec(1) { |x| to_s + x.to_s }

# instance_exec with a splat and no block parameter.
puts b.instance_exec(*[4, 5]) { |*a| a.sum }

# The singleton is made on demand, as CRuby's lazy cref does.
GC.disable
before = ObjectSpace.count_objects[:T_CLASS]
20.times { Box.new(0).instance_exec { @n } }
puts ObjectSpace.count_objects[:T_CLASS] - before
GC.enable
a = Box.new(4)
c = Box.new(5)
a.instance_exec { c.instance_exec { def nested_def = "nested" } }
puts c.nested_def, a.respond_to?(:nested_def)
d = Box.new(6)
d.instance_eval { alias aka secret }
puts d.aka
k = Box.new(7).instance_exec { Class.new { def hi = "hi" } }
puts k.new.hi
puts b.instance_eval { defined?(SCOPED).inspect }
pr = Box.new(8).instance_exec { proc { @n } }
GC.start
puts pr.call
e = Box.new(9)
e.instance_exec { eval("def via_eval = 'ev'") }
puts e.via_eval

# Redefinition must win.
class BasicObject
  def instance_eval(*_args) = "redefined-instance_eval"
end
puts b.instance_eval { secret }
