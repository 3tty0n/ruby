puts :abc.name
puts :abc.name.frozen?
puts :abc.name.equal?(:abc.name)
puts :"a b".name
puts "dyn#{1}".to_sym.name
puts :abc.to_s
puts :abc.to_s.frozen?

puts 3.to_f
puts(-3.to_f)
puts 2.5.to_f
puts 4611686018427387904.to_f
puts((2 ** 70).to_f)
puts 1.0e308.to_f

puts 2.0 ** 0.5
puts 2 ** 0.5
puts 2.0 ** 3
puts 2.0 ** -1
puts 2 ** 10
puts 2 ** -1
puts((-8.0) ** 0.5)
puts((-8.0) ** 3)
puts 0.0 ** -1
puts 1.0e300 ** 2
puts 1.0e300 ** 2.0
puts Float::INFINITY ** 0

puts Math.cos(0)
puts Math.cos(1.0)
puts Math.cos(Math::PI)
puts Math.sqrt(2)

class Plain
end

class WithInit
  def initialize
    @x = 1
  end
  attr_reader :x
end

class Sub < Plain
end

o = Plain.new
puts o.class
puts o.frozen?
puts WithInit.new.x
puts Sub.new.class
begin
  Plain.new(1)
rescue ArgumentError => e
  puts "ArgumentError"
end
puts Array.new(2, 0).inspect
puts String.new("ab")
puts Struct.new(:a).new(3).a

s = +"ab"
s << "cd"
s << ""
puts s
puts s.equal?(s << "e")
s << s
puts s
puts(+"x" << 121)
puts((+"a").force_encoding("ASCII-8BIT") << "b".force_encoding("UTF-8"))
puts((+"a") << "é")
begin
  "frozen".freeze << "x"
rescue FrozenError
  puts "FrozenError"
end
class MyStr < String
end
m = MyStr.new("q")
m << "r"
puts m
puts m.class

puts nil.nil?
puts 1.nil?
puts "s".nil?
puts :s.nil?
puts 1.5.nil?
puts Plain.new.nil?
puts Plain.nil?
puts false.nil?
class Nilish
  def nil? = true
end
puts Nilish.new.nil?
o = Plain.new
def o.nil? = "singleton-nil?"
puts o.nil?

# Every fast path above must give way to a redefinition.
class Symbol
  def name = "redefined-name"
end
class Integer
  def to_f = "redefined-to_f"
  def **(_o) = "redefined-pow"
end
class Float
  def to_f = "redefined-flt-to_f"
  def **(_o) = "redefined-flt-pow"
end
module Math
  def self.cos(_x) = "redefined-cos"
end
class BasicObject
  def initialize = ::Kernel.puts("redefined-initialize")
end
class String
  def <<(_o) = "redefined-ltlt"
end
module Kernel
  def nil? = "redefined-nil?"
end

puts :abc.name
puts 3.to_f
puts 2.5.to_f
puts 2 ** 0.5
puts 2.0 ** 0.5
puts Math.cos(0)
puts((+"a") << "b")
puts 1.nil?
puts nil.nil?
Plain.new
