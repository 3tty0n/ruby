# Struct#initialize only fills slots, so Klass.new can allocate and store
# without a send; every other shape still goes to CRuby.
P = Struct.new(:x, :y)
a = P.new(1, 2)
puts [a.x, a.y, a.to_a, a.class == P, a.size].inspect
puts [P.new(1).to_a, P.new.to_a].inspect
puts a == P.new(1, 2)
puts a.frozen?

begin
  P.new(1, 2, 3)
rescue ArgumentError => e
  puts e.class
end

K = Struct.new(:a, :b, keyword_init: true)
puts K.new(a: 1, b: 2).to_a.inspect
begin
  K.new(1, 2)
rescue ArgumentError => e
  puts e.class
end

class Sub < Struct.new(:m, :n)
  def initialize(m, n = 99)
    super(m, n)
  end
end
puts Sub.new(5).to_a.inspect
puts Sub.new(5, 6).to_a.inspect

class Own < Struct.new(:v)
  def self.new(*args) = "own new"
end
puts Own.new(1)

D = Data.define(:p, :q)
puts D.new(p: 1, q: 2).p
puts D.new(1, 2).q

Big = Struct.new(*(0...12).map { |i| :"f#{i}" })
b = Big.new(*(0...12).to_a)
puts [b.f0, b.f11, b.to_a.size].inspect

S2 = Struct.new(:o)
holder = S2.new(Object.new)
puts holder.o.nil?
puts S2.new([1, 2]).o.inspect

# A member written after construction still reads back.
c = P.new(1, 2)
c.x = 7
puts c.to_a.inspect
puts P.members.inspect
