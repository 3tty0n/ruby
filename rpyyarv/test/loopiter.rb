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
