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

puts "hello".bytesize
puts "\u{6666}ab".bytesize
puts "".bytesize
puts "hello".ascii_only?
puts "\u{6666}ab".ascii_only?
puts "\xff".b.ascii_only?
puts "abc".b.ascii_only?

class WideStr < String
  def bytesize
    :overridden
  end

  def ascii_only?
    :also_overridden
  end
end
puts WideStr.new("abc").bytesize.inspect
puts WideStr.new("abc").ascii_only?.inspect
puts 12.bytesize.inspect rescue puts "NoMethodError bytesize"

pb = +"".b
r = [1.5].pack("E", buffer: pb)
puts r.equal?(pb)
puts pb.encoding.name
puts pb.bytes.inspect
[-2.25].pack("E", buffer: pb)
puts pb.bytesize
puts pb.unpack1("E", offset: 8)

pu = +"xy"
[1.5].pack("E", buffer: pu)
puts pu.encoding.name
puts pu.bytesize

puts [1.5].pack("E").bytes.inspect
puts [1, 2].pack("l<l<").bytes.inspect
puts ["ab"].pack("a4").inspect

begin
  [1.5].pack("E", buffer: "frozen".freeze)
rescue FrozenError => e
  puts "FrozenError: #{e.message}"
end

begin
  [1.5].pack("E", buffer: 7)
rescue TypeError => e
  puts "TypeError: #{e.message}"
end

begin
  [].pack("E", buffer: +"")
rescue ArgumentError => e
  puts "ArgumentError: #{e.message}"
end

pn = +"".b
[3].pack("E", buffer: pn)
puts pn.unpack1("E")

# opt_newarray_send fuses newarray+pack when the element is not a literal.
fv = -0.125
pf = +"".b
[fv].pack("E", buffer: pf)
puts pf.bytes.inspect
puts pf.unpack1("E")
iv = 7
pi = +"".b
[iv].pack("E", buffer: pi)
puts pi.unpack1("E")
puts [fv].pack("E").bytes.inspect
sv = "zz"
puts [sv].pack("a4").inspect
begin
  [fv].pack("E", buffer: "nope".freeze)
rescue FrozenError => e
  puts "FrozenError: #{e.message}"
end

sum = 0.0
names = 0
bytes = 0
ascii = 0
out = +"".b
200_000.times do |i|
  off = 4 + (i & 1) * 8
  v = buff.unpack1("E", offset: off)
  sum += v
  s = buff.byteslice(20, 5).force_encoding(Encoding::UTF_8)
  names += s.bytesize
  ascii += 1 if s.ascii_only?
  out.clear
  [v].pack("E", buffer: out)
  bytes += out.bytesize
end
puts sum
puts names
puts ascii
puts bytes
