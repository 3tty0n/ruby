class Base < String
  def initialize(s)
    super
    @tag = "base"
  end
  attr_reader :tag
end
b = Base.new("hello")
puts b
puts b.tag
puts b.class

class Plain
  def initialize
    super
    @x = 1
  end
  attr_reader :x
end
puts Plain.new.x

class Shouty < Array
  def <<(v)
    super(v.to_s.upcase)
  end
  def to_s
    "Shouty(" + super + ")"
  end
end
s = Shouty.new
s << "a"
s << :b
puts s.inspect
puts s.to_s

class Ghost
  def respond_to_missing?(name, include_private = false)
    name == :ghost || super
  end
end
puts Ghost.new.respond_to?(:ghost)
puts Ghost.new.respond_to?(:nope)
puts Ghost.new.respond_to?(:to_s)

class Counted < Hash
  def []=(k, v)
    @n = (@n || 0) + 1
    super
  end
  attr_reader :n
end
c = Counted.new
c[:a] = 1
c[:b] = 2
puts c.inspect
puts c.n

module Loud
  def speak
    "LOUD " + super
  end
end
class Quiet
  def speak = "quiet"
end
class Both < Quiet
  include Loud
end
puts Both.new.speak

class Err < StandardError
  def initialize(msg = "boom")
    super
  end
end
begin
  raise Err
rescue Err => e
  puts e.message
end

class Deep < Base
  def initialize(s)
    super(s + "!")
  end
end
d = Deep.new("hi")
puts d
puts d.tag

# A super that lands on CRuby's method, which supers again inside CRuby.
class Sub < Struct.new(:a, :b)
  def to_a
    super
  end
end
puts Sub.new(1, 2).to_a.inspect
