# `alias` copies whatever the name resolves to, ancestors included.
class A1
  attr_reader :c
  attr_writer :c
  alias a1 c
  def initialize(x) = @c = x
  def m = 'A1#m'
  private def hidden = 'hidden'
  protected def prot = 'prot'
end

module Mx
  def mixed = 'mixed'
end

class A2 < A1
  include Mx
  alias a2 c
  alias a3 a1
  alias m2 m
  alias mx mixed
  alias hid hidden
  alias pr prot
  alias cw c=
  def m = 'A2#m(' + super + ')'
  def reach(o) = o.pr
end

n = A2.new([1])
p n.a1, n.a2, n.a3, n.m2, n.mx, n.c
n.cw([9])
p n.c
p n.m
p A2.instance_method(:a2).owner, A2.instance_method(:m2).owner
p A2.private_instance_methods(false).sort
p A2.new([1]).send(:hid)
begin
  n.hid
rescue NoMethodError => e
  puts "hid: #{e.class}"
end
begin
  n.pr
rescue NoMethodError => e
  puts "pr: #{e.class}"
end
p n.reach(A2.new([2]))
p A2.instance_methods(false).sort

# alias of a core method inherited from Object
class A3
  alias my_class class
  alias my_inspect inspect
end
p A3.new.my_class
p A3.new.my_inspect.start_with?('#<A3')

# alias_method form, inherited
class A4 < A1
  alias_method :b1, :c
  alias_method :b2, :m
end
p A4.new([3]).b1, A4.new([3]).b2

# redefining the original leaves the alias alone
class A5 < A1
  alias orig m
  def m = 'A5#m'
end
p A5.new([4]).orig, A5.new([4]).m

# alias in a module, then included
module Mz
  def zz = 'zz'
  alias zz2 zz
end
class A6; include Mz; end
p A6.new.zz2

# alias of a singleton-inherited class method
class A7
  def self.mk = 'mk'
end
class A8 < A7
  class << self
    alias mk2 mk
  end
end
p A8.mk2
