# super into a method define_method copied from another module's UnboundMethod
# (ActiveSupport::CodeGenerator's shape): the copy must run its own body.
cache = Module.new
cache.module_eval("def x; :from_gam; end; def y(a); [:gam, a]; end")

gam = Module.new
gam.send(:define_method, :x, cache.instance_method(:x))
gam.send(:define_method, :y, cache.instance_method(:y))

class C; end
C.include(gam)
class C
  def x = super
  def y(a) = super
  def z = :own
end

p C.new.x
p C.new.y(7)
p C.new.z
p C.instance_method(:x).super_method.owner == gam

# The copy is reachable without a super, too.
class D; end
D.include(gam)
p D.new.x
