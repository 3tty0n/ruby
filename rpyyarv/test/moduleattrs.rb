module Outer; end
module Outer::Inner
  attr_accessor :pal
  attr_reader :ro
  attr_writer :wo
  def initialize_ro(v) = @ro = v
end
class Canvas
  include Outer::Inner
end
c = Canvas.new
c.pal = [1, 2, 3]
p c.pal
p c.pal[1]
c.initialize_ro(:r)
p c.ro
c.wo = 9
p c.instance_variable_get(:@wo)
p Canvas.new.pal
p Canvas.instance_method(:pal).owner
p c.respond_to?(:pal)

module Mixin
  attr_accessor :shared
end
class A2; include Mixin; end
class B2; include Mixin; end
a = A2.new; b = B2.new
a.shared = 1; b.shared = 2
p [a.shared, b.shared]

# A redefinition on the including class wins over the module's.
class A2
  def shared = "own"
end
p a.shared
p b.shared

module Deep
  attr_accessor :d
end
module Mid
  include Deep
end
class Leaf; include Mid; end
l = Leaf.new
l.d = 7
p l.d
