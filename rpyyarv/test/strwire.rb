buff = ("\x00\x01\x02\x03" + [1.5, -2.25].pack("EE") + "hello").b

s = buff.byteslice(20, 5).force_encoding(Encoding::UTF_8)
puts s.encoding.name
puts s
puts s == "hello"

t = buff.byteslice(20, 5).force_encoding("UTF-8")
puts t.encoding.name
puts t.valid_encoding?

begin
  "frozen".freeze.force_encoding(Encoding::UTF_8)
rescue FrozenError => e
  puts "FrozenError: #{e.message}"
end

begin
  +"x".force_encoding("no-such-encoding")
rescue ArgumentError => e
  puts "ArgumentError: #{e.message}"
end

begin
  (+"x").force_encoding(3)
rescue TypeError => e
  puts "TypeError: #{e.message}"
end

u = (+"abc").force_encoding(Encoding::UTF_16LE)
puts u.encoding.name
puts u.bytesize

puts buff.unpack1("E", offset: 4)
puts buff.unpack1("E", offset: 12)
puts (buff.byteslice(4, 8)).unpack1("E")
puts buff.unpack1("E")
puts buff.unpack1("l<", offset: 4)
puts "short: #{"1234567".unpack1("E").inspect}"
puts "short2: #{buff.unpack1("E", offset: 21).inspect}"

begin
  buff.unpack1("E", offset: 100)
rescue ArgumentError => e
  puts "ArgumentError: #{e.message}"
end

begin
  buff.unpack1("E", offset: -1)
rescue ArgumentError => e
  puts "ArgumentError: #{e.message}"
end

sum = 0.0
names = 0
200_000.times do |i|
  off = 4 + (i & 1) * 8
  sum += buff.unpack1("E", offset: off)
  names += buff.byteslice(20, 5).force_encoding(Encoding::UTF_8).bytesize
end
puts sum
puts names
