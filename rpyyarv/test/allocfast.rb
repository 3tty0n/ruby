class Plain
  attr_accessor :x

  def initialize
    @x = :never_run
  end

  def tag
    "plain #{@x.inspect}"
  end
end

o = Plain.allocate
puts o.class
puts o.x.inspect
puts o.tag
puts Plain.allocate.tag

class Sentinel
  def self.allocate
    :sentinel
  end
end
puts Sentinel.allocate.inspect

class Overridden
end
def Overridden.allocate
  :singleton_override
end
puts Overridden.allocate.inspect

S = Struct.new(:a, :b)
s = S.allocate
puts s.class
puts s.a.inspect
s.a = 3
puts s.a

u = Class.allocate
puts u.class
begin
  u.allocate
rescue TypeError => e
  puts "TypeError: #{e.message}"
end

begin
  Plain.singleton_class.allocate
rescue TypeError => e
  puts "TypeError: #{e.message}"
end

sum = 0
200_000.times do
  a = Plain.allocate
  a.x = 1
  sum += a.x
end
puts sum
