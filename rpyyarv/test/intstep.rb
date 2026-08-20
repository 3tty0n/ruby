# Integer#step with a block: the native loop must yield exactly what CRuby
# does, and hand every other shape of the call back to CRuby.

a = []
1.step(10, 3) { |i| a << i }
puts a.inspect

a = []
10.step(1, -3) { |i| a << i }
puts a.inspect

a = []
1.step(4) { |i| a << i }
puts a.inspect

a = []
4.step(1) { |i| a << i }
puts a.inspect

a = []
5.step(5) { |i| a << i }
puts a.inspect

a = []
-3.step(3, 2) { |i| a << i }
puts a.inspect

puts(3.step(9, 2) { |_i| }.inspect)

a = []
1.step(10) { |i| a << i; break if i == 3 }
puts a.inspect

puts(1.step(10) { |i| break i * 100 if i == 2 }.inspect)

a = []
1.step(2.5, 0.5) { |i| a << i }
puts a.inspect

begin
  1.step(10, 0) { |_i| }
rescue => e
  puts e.class
end

puts 1.step(3).to_a.inspect
puts 1.step(by: 2, to: 7).to_a.inspect

a = []
1.step(to: 7, by: 3) { |i| a << i }
puts a.inspect

# A redefined Integer#step must win over the fast path.
class Integer
  alias_method :orig_step, :step
  def step(*args, &blk) = "redefined"
end
puts 1.step(5, 2) { |_i| }
class Integer
  remove_method :step
  alias_method :step, :orig_step
end
a = []
1.step(5, 2) { |i| a << i }
puts a.inspect
