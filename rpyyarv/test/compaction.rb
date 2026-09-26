# Every kind of host value RPyYARV retains by address, read again after the
# most aggressive compaction the host offers.  Output must match CRuby.
def compact!
  GC.verify_compaction_references(expand_heap: true, toward: :empty)
  GC.compact
end

# constant values: cached per site and per (cbase, name), folded into traces
S = String.new("hello world")
A = [1, 2, 3]
H = { a: 1 }
class K
  def initialize; @v = 7; end
  def v; @v; end
end
O = K.new
def consts; S.length + A.length + H.size + O.v; end
n = 0
200_000.times { n += consts }
puts n
compact!
n = 0
200_000.times { n += consts }
puts n
puts S, A.inspect, H.inspect, O.v

# method bodies: the ISeq behind a trampoline and Method#source_location
def located; :here; end
m = method(:located)
puts m.source_location.inspect
compact!
puts m.source_location.inspect, located, m.call

# a class defined after warm-up, its constant and its singleton method
module Late
  X = "x" * 3
  def self.ping; X.size; end
end
puts Late.ping
compact!
puts Late.ping, Late::X

# owner caches: super through a module, respond_to?, kind_of?
module M; def who; "M>" + super; end; end
class Base; def who; "Base"; end; end
class Derived < Base; include M; def who; "D>" + super; end; end
d = Derived.new
puts d.who, d.respond_to?(:who), d.kind_of?(M)
compact!
puts d.who, d.respond_to?(:who), d.kind_of?(M)

# blocks handed to the host, held across a compaction inside the callback
r = [1, 2, 3].map { |x| compact!; x * 2 }
puts r.inspect

# a Proc kept only by the host, defined before the move
pr = proc { |x| S + x.to_s }
h = { k: pr }
compact!
puts h[:k].call(1)

# an Encoding looked up by name and cached
e = Encoding.find("UTF-8")
compact!
puts e == Encoding.find("UTF-8")

# structs: member index cache keyed by class
P = Struct.new(:x, :y)
p1 = P.new(1, 2)
puts p1.x + p1.y
compact!
puts p1.x + p1.y

# a suspended fiber whose frames refer back to it
f = Fiber.new { compact!; Fiber.yield 1; compact!; 2 }
puts f.resume
compact!
puts f.resume

# exceptions saved across the boundary
begin
  [1].each { compact!; raise "boom" }
rescue => err
  compact!
  puts err.message
end
puts GC.stat[:compact_count] > 5
