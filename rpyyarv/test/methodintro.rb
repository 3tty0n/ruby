# source_location, arity and parameters of a Ruby def, plus ruby2_keywords.
class C
  def a; end
  private def b(x, *r); end
  def self.c(k: 1); end
end

def loc(v)
  v.nil? ? "nil" : [File.basename(v[0]), v[1]].inspect
end

puts loc(C.instance_method(:a).source_location)
puts loc(C.instance_method(:b).source_location)
puts loc(C.method(:c).source_location)
puts C.instance_method(:b).arity
puts C.instance_method(:b).parameters.inspect
puts C.method(:c).parameters.inspect
puts C.private_method_defined?(:b)

# private def must fire method_added exactly once, as CRuby does.
class D
  def self.method_added(n) = puts("added #{n}")
  def e; end
  private def f; end
end

def sink(*a, **k) = [a, k]
ruby2_keywords def fwd(*a) = sink(*a)
puts fwd(1, {z: 2}).inspect
puts fwd(1, **{z: 2}).inspect

module M
  def self.mk(name)
    define_method(name) { |*a| sink(*a) }
    ruby2_keywords(name)
  end
  mk(:blk)
  module_function :blk
end
puts M.blk(1, **{z: 2}).inspect
