p [1,2].each.class
p 3.times.class
p (1..3).each.class
p [1,2].each_index.class
p 1.upto(3).class
p 3.downto(1).class
p 1.step(5,2).class
p [1,2,3].each.next
p 3.times.to_a
p (1..3).each.to_a
p [10,20].each_index.to_a
p 1.upto(3).to_a
p 3.downto(1).to_a
e = [4,5].each
p e.next
p e.next
begin
  e.next
rescue StopIteration
  p :stop
end
n = 0
[1,2,3].each { |x| n += x }
p n
p 3.times { }
p [1,2].each_with_index.to_a
