n = 0
loop do
  n += 1
  break if n > 3
end
puts n
r = loop do
  break "brk"
end
puts r
e = [1,2].each
puts(loop { e.next })
puts(loop { break 7 })
def m
  loop { return "ret" }
end
puts m
puts loop.class
i = 0
r = loop do
  i += 1
  next if i < 5
  break i * 2
end
p r
def outer
  loop { loop { return :inner } }
end
p outer
c = 0
begin
  loop do
    c += 1
    raise "boom" if c > 2
  end
rescue RuntimeError => e
  p [c, e.message]
end
p loop { break }

# ---- native Array#each_with_index ----
acc = []
ret = %w[a b c].each_with_index { |s, i| acc << "#{s}#{i}" }
p acc
p ret == %w[a b c]
p [10, 20, 30].each_with_index { |v, i| break v + i if v == 20 }
p [].each_with_index { |v, i| raise "unreachable" }
[5, 6].each_with_index { |pair| p pair }
shrink = [1, 2, 3, 4]
shrink.each_with_index { |v, i| p [v, i]; shrink.pop if i == 0 }
grow = [1, 2]
grow.each_with_index { |v, i| p [v, i]; grow << 9 if i == 1 && grow.size < 4 }
class MyAry < Array; end
sub = MyAry.new([7, 8])
sub.each_with_index { |v, i| p [v, i] }
p [1, 2].each_with_index.to_a
