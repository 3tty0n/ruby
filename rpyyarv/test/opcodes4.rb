# opt_nil_p, opt_str_freeze, opt_case_dispatch and opt_newarray_send.

def classify(x)
  case x
  when 1 then "one"
  when 2 then "two"
  when 3 then "three"
  else "many"
  end
end

def named(s)
  case s
  when "a" then :first
  when "b" then :second
  else :other
  end
end

def symbolic(s)
  case s
  when :red then 1
  when :green then 2
  when :blue then 3
  else 0
  end
end

i = 0
while i < 6
  puts classify(i)
  i = i + 1
end

puts named("a")
puts named("b")
puts named("zz")

puts symbolic(:red)
puts symbolic(:green)
puts symbolic(:blue)
puts symbolic(:violet)

# A dispatchable key mixed with a non-dispatchable one keeps the sequential tests.
def mixed(x)
  case x
  when 1 then "int"
  when Float then "float"
  when "s" then "str"
  else "none"
  end
end

puts mixed(1)
puts mixed(2.5)
puts mixed("s")
puts mixed(nil)

# Dense integer cases, the shape a CDHASH dispatch would take.
def dense(n)
  case n
  when 0 then "zero"
  when 1 then "one"
  when 2 then "two"
  when 3 then "three"
  when 4 then "four"
  when 5 then "five"
  when 6 then "six"
  when 7 then "seven"
  else "out"
  end
end

d = -1
acc = ""
while d < 9
  acc = acc + dense(d) + ","
  d = d + 1
end
puts acc

# String cases in a loop, the shape json's read_value has.
def chars(c)
  case c
  when "n" then 1
  when "t" then 2
  when "f" then 3
  when '"' then 4
  when "[" then 5
  when "{" then 6
  when "-", "0", "1", "2" then 7
  else 0
  end
end

src = "nt\"f[{-2x0"
sum = 0
k = 0
while k < src.length
  sum = sum + chars(src[k])
  k = k + 1
end
puts sum

# Keys no dispatch hash could answer for.
puts dense(2.0)
puts dense(nil)
puts chars(:n)

s = "frozen".freeze
puts s
puts s.frozen?

t = 0
while t < 3
  puts "loop".freeze.frozen?
  t = t + 1
end

puts nil.nil?
puts 1.nil?
puts "x".nil?
puts [].nil?

class NeverNil
  def nil?
    false
  end
end
puts NeverNil.new.nil?

a = 1
b = 5
c = 3
puts [a, b, c].min
puts [a, b, c].max
puts [b, a].min
puts [c].max
puts [a, b, c].include?(5)
puts [a, b, c].include?(9)
puts [a, b].hash == [a, b].hash
x = 65
y = 66
puts [x, y, 67].pack("C*")

n = 0
total = 0
while n < 4
  total = total + [n, 2].max + [n, 2].min
  n = n + 1
end
puts total

class NilClass
  def nil?
    "redefined"
  end
end
puts nil.nil?
puts 2.nil?

# A redefined Integer#=== every case above must go through.
class Integer
  def ===(other)
    true
  end
end
puts dense(99)
puts dense(4)
puts chars("t")
