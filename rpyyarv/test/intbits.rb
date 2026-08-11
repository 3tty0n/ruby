# Integer#[], #<< and #-@ on the native path, and every receiver that must fall back.

[0, 1, -1, 7, -7, 0x2b, 4611686018427387903, -4611686018427387904].each do |n|
  puts [0, 1, 5, 61, 62, 63, 200].map {|i| n[i] }.inspect
end

puts((2**200)[199])
puts(0x2b[-1]) rescue puts "raised"
puts(0x2b[1..3])

[0, 1, -1, 3, -3, 4611686018427387903, -4611686018427387904].each do |n|
  puts [0, 1, 2, 60, 61, 62, 63, 200].map {|s| (n << s).to_s }.inspect
end
puts((1 << -2))
puts((2**200 << 3))

[0, 1, -1, 4611686018427387903, -4611686018427387904].each {|n| puts(-n) }
puts(-(2**200))
puts(-(-3.5))

class Integer
  def [](i)
    "redefined-aref"
  end

  def <<(s)
    "redefined-lshift"
  end

  def -@
    "redefined-uminus"
  end
end

puts 5[1]
puts(5 << 2)
puts(-5)
