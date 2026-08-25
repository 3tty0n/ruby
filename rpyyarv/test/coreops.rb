# ---- Array#first / #last ----

puts [1, 2, 3].first
puts [1, 2, 3].last
puts [].first.inspect
puts [].last.inspect
puts [42].first
puts [42].last

class MyArray < Array
  def first
    :first_redefined
  end
end
ma = MyArray.new([1, 2, 3])
puts ma.first
puts ma.last

# ---- Integer#to_i / #to_int ----

puts 5.to_i
puts(-5.to_i)
puts 5.to_int
class Integer
  def to_i
    :to_i_redefined
  end
end
puts 5.to_i
puts 5.to_int

# ---- Float#abs ----

puts 1.5.abs
puts(-1.5.abs)
puts 0.0.abs
puts(-0.0.abs)
class Float
  def abs
    :abs_redefined
  end
end
puts 1.5.abs
puts(-1.5.abs)

# ---- String#to_sym ----

puts "hello".to_sym.inspect
puts "".to_sym.inspect
class String
  def to_sym
    :to_sym_redefined
  end
end
puts "hello".to_sym

# ---- String#ord ----

puts "a".ord
puts "abc".ord
begin
  puts "".ord
rescue ArgumentError => e
  puts e.class
end
puts "\xE2\x98\x83".force_encoding("UTF-8").ord
class String
  def ord
    :ord_redefined
  end
end
puts "a".ord

# ---- String#[] with a single Fixnum index ----

s = "hello"
puts s[0]
puts s[4]
puts s[-1]
puts s[100].inspect
puts s[-100].inspect
puts "\xE2\x98\x83".force_encoding("UTF-8")[0].bytesize
class String
  def [](_idx)
    :aref_redefined
  end
end
puts s[0]
