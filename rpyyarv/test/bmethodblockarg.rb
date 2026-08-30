# A block written at the call site must reach a bmethod's &parameter, while
# yield in the body still takes the block of the frame the body was written in.

class T
  define_method(:go) { |&blk| blk && blk.call }
  define_method(:one) { |x, &blk| [x, blk && blk.call] }
  define_method(:given) { block_given? }
end

p T.new.go { :called }
p T.new.go
p T.new.one(1) { :called }
p T.new.given { 1 }

def defining_block
  Class.new do
    define_method(:z) { yield }
  end
end
k = defining_block { :from_defining }
puts k.new.z { :from_call }

# A splat call site and a super chain both take the same route.
class Base
  def greet(&b); ['base', b && b.call]; end
end
class Derived < Base
  define_method(:greet) { |&b| ['derived'] + super(&b) }
end
args = []
p Derived.new.greet { :sup }
p Derived.new.send(:greet, *args) { :sup2 }

require 'delegate'
class Box
  def each; yield 1; yield 2; :done; end
  def [](i); i * 2; end
end
class BoxD < DelegateClass(Box); end
d = BoxD.new(Box.new)
p d[21]
seen = []
p d.each { |x| seen << x }
p seen
s = SimpleDelegator.new(Box.new)
seen2 = []
p s.each { |x| seen2 << x }
p seen2
