# Class.new/Module.new with a block: rb_mod_initialize module_execs it, so a
# def inside lands on the new class as a public method, not on Object.

C = Class.new do
  def hello; 'hello'; end
  def initialize(v); @v = v; end
  attr_reader :v
end
puts C.new(7).hello
puts C.new(7).v
puts C.instance_methods(false).sort.inspect
puts Object.instance_methods.include?(:hello)

class Base
  def who; 'base'; end
end
D = Class.new(Base) do
  def who; 'derived+' + super; end
end
puts D.new.who
puts D.superclass

M = Module.new do
  def mixed; 'mixed'; end
end
puts M.instance_methods.inspect
class UsesM; include M; end
puts UsesM.new.mixed

puts Class.new { |k| k.class_eval { def viab; 'viab'; end } }.new.viab
E = Class.new do
  self
end
puts E.name.inspect

F = Class.new do
  def pub; priv; end
  private
  def priv; 'priv'; end
end
puts F.new.pub
begin
  F.new.priv
rescue NoMethodError => e
  puts e.class
end

G = Class.new do
  Class.new do
    def inner; 'inner'; end
  end.new.tap { |o| puts o.inner }
end

# A block that takes the class as its parameter.
I = Class.new { |k| k.send(:define_method, :made) { 'made' } }
puts I.new.made

# No block: unchanged.
puts Class.new(Base).new.who
puts Module.new.instance_methods.inspect

# Struct.new and Data.define module_exec their block on the class they make,
# exactly as Class.new does (struct.c).
S2 = Struct.new(:a, :b) do
  def sum; a + b; end
  def self.build(x) = new(x, x)
end
puts [S2.new(1, 2).sum, S2.build(3).sum].inspect
puts S2.instance_methods(false).sort.inspect
puts Object.private_instance_methods.include?(:sum)
puts Struct.new(:x) { def dbl = x * 2 }.new(4).dbl
puts Struct.new(:q).new(9).q
D3 = Data.define(:m) do
  def shout = "#{m}!"
end
puts D3.new(m: "hi").shout
puts Data.define(:n).new(n: 1).n
K2 = Struct.new(:a, keyword_init: true) do
  def twice = a * 2
end
puts K2.new(a: 5).twice
class SubS < Struct.new(:v)
  def plus1 = v + 1
end
puts SubS.new(1).plus1
