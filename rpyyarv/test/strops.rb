# String fast paths: ==, !=, length, size and [] must answer what CRuby does.

a = "hello"
b = "hello"
c = "hellO"
empty = ""

puts a == b
puts a == c
puts a == a
puts a == "hell"
puts a != b
puts a != c
puts empty == ""
puts empty != ""

# Non-String arguments: false without asking, whatever the operand is.
puts a == 5
puts a == nil
puts a == :hello
puts a == 1.5
puts a == true
puts a != 5
puts a != nil
puts a == [1, 2]
puts a == { 1 => 2 }
puts 5 == a
puts nil == a
puts :hello == a

puts a.length
puts a.size
puts empty.length
puts empty.size
puts "a".length

# Multibyte: length counts characters, not bytes. Built through pack, since a
# non-ascii literal does not survive RPyYARV's loader with its encoding.
m = [26085, 26412, 35486].pack("U*")
m2 = [26085, 26412, 35486].pack("U*")
puts m.length
puts m.size
puts m.bytesize
puts m == m2
puts m == a
puts m != m2
puts m[0] == m2[0]
puts m[1] == m2[1]
puts m[3].inspect
puts m[-1] == m2[2]
puts m[0].length
puts m[0].bytesize

# Mixed ascii/multibyte comparison.
puts a == m
puts m == a

puts a[0]
puts a[1]
puts a[4]
puts a[5].inspect
puts a[6].inspect
puts a[-1]
puts a[-5]
puts a[-6].inspect
puts empty[0].inspect
puts empty[-1].inspect
puts a[0].class
puts a[0].frozen?
puts a[0].length
puts a[0] == "h"

# A range and a string index still go to CRuby.
puts a[1, 3]
puts a[1..3]
puts a["ell"]
puts a["xyz"].inspect

frozen = "frozen".freeze
puts frozen.frozen?
puts frozen == "frozen"
puts frozen != "frozen"
puts frozen.length
puts frozen.size
puts frozen[2]

bytes = "abc"
puts bytes.getbyte(0)
puts bytes.getbyte(-1)
puts bytes.getbyte(99).inspect
puts bytes.setbyte(1, 300)
puts bytes.bytes.inspect
begin
  frozen.setbyte(0, 1)
rescue FrozenError
  puts "FrozenError on setbyte"
end

# A subclass may redefine anything, so it takes the send.
class MyStr < String
  def length
    42
  end

  def getbyte(index)
    999
  end

  def setbyte(index, value)
    :setbyte
  end
end
sub = MyStr.new("abcd")
puts sub.length
puts sub.size
puts sub == "abcd"
puts "abcd" == sub
puts sub[1]
puts sub.class
puts sub.getbyte(0)
puts sub.setbyte(0, 1)

n = 0
i = 0
while i < 2000
  n += 1 if a == b
  n += 1 if a != c
  n += a.length
  n += 1 if a[i % 5] == "h"
  i += 1
end
puts n

# A receiver no local holds: the fast path must keep it alive across the
# allocation the one-character result costs.
n2 = 0
i = 0
while i < 2000
  n2 += 1 if ("hel" + "lo")[i % 5] == "l"
  n2 += ("hel" + "lo").length
  n2 += 1 if ("hel" + "lo") == "hello"
  i += 1
end
puts n2

# Redefinitions: every fast path above must give way from here on.
class String
  def length
    -1
  end

  def [](*args)
    :aref
  end

  def ==(other)
    :eq
  end

  def getbyte(index)
    :getbyte
  end

  def setbyte(index, value)
    :setbyte
  end
end

puts a.length
puts a.size
puts a[0].inspect
puts (a == b).inspect
puts (a != b).inspect
puts a.getbyte(0)
puts a.setbyte(0, 1)
p :"dynamic-#{1}"
