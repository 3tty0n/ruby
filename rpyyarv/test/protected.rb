# protected: an explicit receiver is allowed while the caller is kin, and
# refused otherwise. A `protected :sym` after a `private` pragma has to move
# the method out of private, which is how rubocop-ast declares its API.
class A
  def call_other(o) = o.prot
  def call_self = prot
  protected
  def prot = 'prot'
end
a = A.new
p a.call_other(A.new)
p a.call_self
begin; a.prot; rescue NoMethodError => e; p [:outside, e.message[0, 30]]; end

class B
  def prot2 = 'p2'
  protected :prot2
  def use(o) = o.prot2
end
p B.new.use(B.new)

class C2 < A
  def cross(o) = o.prot
end
p C2.new.cross(A.new)

module Mx
  def self.included(b); end
  def mprot = 'mp'
  protected :mprot
  def usem(o) = o.mprot
end
class D2; include Mx; end
p D2.new.usem(D2.new)

p A.new.respond_to?(:prot)
p A.new.respond_to?(:prot, true)
p A.protected_instance_methods(false).inspect
p A.private_instance_methods(false).inspect

class E2
  private
  def hidden = 'h'
  def promoted = 'p'
  protected :promoted
  public
  def reach(o) = o.promoted
end
p E2.new.reach(E2.new)
begin; E2.new.promoted; rescue NoMethodError => e; p e.message[0, 24]; end
begin; E2.new.hidden; rescue NoMethodError => e; p e.message[0, 22]; end
p E2.protected_instance_methods(false).inspect
p E2.private_instance_methods(false).sort.inspect

class F2
  def cmp(o) = value <=> o.value
  protected def value = 42
end
p F2.new.cmp(F2.new)
p F2.protected_instance_methods(false).inspect

class G2 < F2; end
p G2.new.cmp(G2.new)
p F2.new.cmp(G2.new)
