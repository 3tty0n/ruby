# ---- Symbol == / != / equal? ----

a = :alpha
b = :beta
puts a == :alpha
puts a == b
puts a != b
puts a != :alpha
puts a.equal?(:alpha)
puts a.equal?(b)
puts(a == 'alpha')
puts(a == 1)
puts(a == nil)
dyn = ('dyn' + '2').to_sym
puts(dyn == :dyn2)
puts(dyn.equal?(:dyn2))
puts(nil == a)
puts(['x', :x, 1].map { |v| v == :x }.inspect)

syms = [:one, :two, :three]
n = 0
i = 0
while i < 3
  n += 1 if syms[i] == :two
  n += 1 if syms[i] != :two
  i += 1
end
puts n

# ---- Integer ^ ----

puts(5 ^ 3)
puts(0 ^ 0)
puts(-1 ^ 0)
puts(-1 ^ -1)
puts(-5 ^ 3)
puts(123456789 ^ 987654321)
puts(4611686018427387903 ^ 1)
puts(-4611686018427387904 ^ 1)
puts((2**70) ^ 1)
puts(1 ^ (2**70))
puts(true ^ false)
puts(true ^ true)
begin
  puts(1 ^ nil)
rescue TypeError => e
  puts "TypeError #{e.message}"
end
begin
  puts(1 ^ 2.0)
rescue TypeError, NoMethodError => e
  puts e.class
end

x = 0
i = 0
while i < 100
  x = x ^ i
  i += 1
end
puts x

# ---- Integer >> ----

puts(1024 >> 3)
puts(1 >> 0)
puts(1 >> 1)
puts(1 >> 1000)
puts(-1 >> 1)
puts(-1 >> 1000)
puts(-7 >> 1)
puts(-7 >> 2)
puts(-4611686018427387904 >> 62)
puts(4611686018427387903 >> 62)
puts(1 >> -3)
puts(1 >> -100)
puts((2**70) >> 60)
puts(1024 >> (2**70))
begin
  puts(1 >> nil)
rescue TypeError => e
  puts "TypeError #{e.message}"
end

y = 0
i = 0
while i < 100
  y += (1234567 >> (i % 20))
  i += 1
end
puts y

# ---- Range begin / end / exclude_end? ----

r = 1..5
puts r.begin
puts r.end
puts r.exclude_end?
e = 1...5
puts e.begin
puts e.end
puts e.exclude_end?
puts((1..).end.inspect)
puts((..5).begin.inspect)
puts(('a'..'c').begin)
puts(('a'..'c').end)
puts((1.5..2.5).begin)

acc = []
(1..5).each { |v| acc << v }
(1...5).each { |v| acc << v }
puts acc.inspect

total = 0
i = 0
while i < 200
  (1..4).each { |v| total += v }
  i += 1
end
puts total

# A Range subclass keeps its own overrides.
class MyRange < Range
  def begin
    42
  end
end
mr = MyRange.new(1, 5)
puts mr.begin
puts mr.end
puts mr.exclude_end?

# Anything that merely answers to these names is untouched.
class Bookend
  def begin
    'B'
  end

  def end
    'E'
  end

  def exclude_end?
    'X'
  end
end
bk = Bookend.new
puts bk.begin
puts bk.end
puts bk.exclude_end?

# ---- deoptimisation: each fast path gives way to a redefinition ----

class Integer
  def ^(_other)
    :xor_redefined
  end

  def >>(_other)
    :shift_redefined
  end
end
puts(5 ^ 3)
puts(1024 >> 3)

class Range
  def begin
    :begin_redefined
  end

  def end
    :end_redefined
  end

  def exclude_end?
    :excl_redefined
  end
end
puts((1..5).begin)
puts((1..5).end)
puts((1..5).exclude_end?)

class Symbol
  def ==(_other)
    :eq_redefined
  end
end
puts(:alpha == :alpha)
puts(:alpha == :beta)
puts(:alpha.equal?(:alpha))
puts(:alpha.equal?(:beta))
