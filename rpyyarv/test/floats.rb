# ---- Float op Float ----

puts(1.5 + 2.25)
puts(1.5 - 2.25)
puts(1.5 * 2.25)
puts(1.5 / 2.25)
puts(1.5 < 2.25)
puts(1.5 <= 1.5)
puts(1.5 > 2.25)
puts(1.5 >= 1.5)
puts(1.5 == 1.5)
puts(1.5 != 1.5)

# ---- NaN in every comparison ----

nan = 0.0 / 0.0
puts nan
puts(nan == nan)
puts(nan != nan)
puts(nan < nan)
puts(nan <= nan)
puts(nan > nan)
puts(nan >= nan)
puts(nan < 1.0)
puts(nan <= 1.0)
puts(nan > 1.0)
puts(nan >= 1.0)
puts(1.0 < nan)
puts(1.0 <= nan)
puts(nan == 1)
puts(nan != 1)
puts(1 == nan)
puts(nan + 1.0)
puts(nan * 0.0)

# ---- +0.0 / -0.0 ----

pz = 0.0
nz = -0.0
puts(pz == nz)
puts(pz != nz)
puts(1.0 / pz)
puts(1.0 / nz)
puts(-1.0 / pz)
puts(pz + nz)
puts(nz + nz)
puts(pz * -1.0)
puts(nz.to_s)
puts(pz < nz)
puts(pz <= nz)
puts(0.0 == 0)
puts(-0.0 == 0)

# ---- Infinity ----

inf = 1.0 / 0.0
ninf = -1.0 / 0.0
puts inf
puts ninf
puts(inf + 1.0)
puts(inf - inf)
puts(inf * 0.0)
puts(inf / inf)
puts(inf * 2.0)
puts(inf > 1.0e300)
puts(ninf < -1.0e300)
puts(inf == inf)
puts(inf != ninf)
puts(1.0 / inf)
puts(-1.0 / inf)

# ---- division by zero, Float against Integer ----

puts(3.0 / 0)
puts(-3.0 / 0)
puts(0.0 / 0)
puts(3 / 0.0)
puts(0 / 0.0)
begin
  puts(3 / 0)
rescue ZeroDivisionError => e
  puts "ZeroDivisionError #{e.message}"
end
puts(7 / 2)
puts(7 / 2.0)
puts(7.0 / 2)
puts(-7 / 2)
puts(-7 / 2.0)

# ---- mixed Integer/Float, both orders, every operator ----

[[3, 2.5], [-3, 2.5], [3, -2.5]].each do |i, f|
  puts(i + f)
  puts(f + i)
  puts(i - f)
  puts(f - i)
  puts(i * f)
  puts(f * i)
  puts(i / f)
  puts(f / i)
  puts(i < f)
  puts(f < i)
  puts(i <= f)
  puts(f <= i)
  puts(i > f)
  puts(f > i)
  puts(i >= f)
  puts(f >= i)
  puts(i == f)
  puts(f == i)
  puts(i != f)
  puts(f != i)
end

puts(1 == 1.0)
puts(1.0 == 1)
puts(1 != 1.0)
puts(1.0 != 1)
puts(2 == 1.9999999999999999)
puts(0 == 0.0)

# ---- doubles no flonum can hold, as operand and as result ----

big = 1.0e300
small = 1.0e-300
puts big
puts small
puts(big * 10.0)
puts(big + big)
puts(small / 10.0)
puts(small * small)
puts(big > small)
puts(big == 1.0e300)
puts(-0.0 * 1.0)
puts(1.0e-320)
puts(1.727233711018889e-77)
puts(1.727233711018889e-77 * 1.0)
puts(1.727233711018889e-77 == 1.727233711018889e-77)
puts(2.0**-1000)
puts(4.9e-324)

# ---- Bignum mixed with Float ----

bn = 2**70
puts(bn + 1.0)
puts(1.0 + bn)
puts(bn * 2.0)
puts(2.0 * bn)
puts(bn - 1.0)
puts(1.0 - bn)
puts(bn / 2.0)
puts(2.0 / bn)
puts(bn > 1.0)
puts(1.0 > bn)
puts(bn == 1.0)
puts(1.0 == bn)
puts(bn.to_f)

# ---- the fixnum extremes ----

fmax = 4611686018427387903
fmin = -4611686018427387904
puts(fmax + 0.0)
puts(0.0 + fmax)
puts(fmin + 0.0)
puts(fmax * 1.0)
puts(fmax < 4.611686018427388e18)
puts(fmax > 4.611686018427388e18)
puts(fmax == 4.611686018427388e18)
puts(4.611686018427388e18 == fmax)
puts(4.611686018427388e18 <= fmax)
puts(fmin == -4.611686018427388e18)
puts(9007199254740993 == 9007199254740992.0)
puts(9007199254740992.0 == 9007199254740993)
puts(9007199254740993 < 9007199254740992.0)

# ---- Math.sqrt ----

puts(Math.sqrt(4.0))
puts(Math.sqrt(2.0))
puts(Math.sqrt(4))
puts(Math.sqrt(0.0))
puts(Math.sqrt(-0.0))
puts(Math.sqrt(0))
puts(Math.sqrt(1.0e300))
puts(Math.sqrt(1.0 / 0.0))
puts(Math.sqrt(0.0 / 0.0))
puts(Math.sqrt(9007199254740993))
begin
  puts(Math.sqrt(-1.0))
rescue Math::DomainError => e
  puts "DomainError #{e.message}"
end
begin
  puts(Math.sqrt(-1))
rescue Math::DomainError => e
  puts "DomainError #{e.message}"
end
begin
  puts(Math.sqrt("2"))
rescue TypeError => e
  puts "TypeError"
end

# ---- a loop the JIT gets to compile ----

def mix(n)
  x = 0.0
  i = 0
  while i < n
    x = x + i * 0.5
    x = x - 0.25
    x = x / 1.0001
    i += 1
  end
  x
end
puts mix(2000)

def cmp(n)
  hits = 0
  i = 0
  while i < n
    f = i * 0.5
    hits += 1 if f < 100.0
    hits += 1 if f <= 100.0
    hits += 1 if f > 100.0
    hits += 1 if f >= 100.0
    hits += 1 if f == 100.0
    hits += 1 if f != 100.0
    hits += 1 if i < f
    hits += 1 if f < i
    i += 1
  end
  hits
end
puts cmp(500)

def roots(n)
  s = 0.0
  i = 1
  while i < n
    s += Math.sqrt(i * 1.0)
    i += 1
  end
  s
end
puts roots(1000)

# ---- deoptimisation: a redefined Float operator must be used ----

class Float
  def +(other)
    :plus
  end

  def <(other)
    :less
  end

  def ==(other)
    :equal
  end
end

puts((1.5 + 2.5).inspect)
puts((1.5 < 2.5).inspect)
puts((1.5 == 1.5).inspect)
puts((1.5 == 1).inspect)
puts((1.5 - 2.5).inspect)
puts((1.5 * 2.0).inspect)
puts((1 + 2.5).inspect)
puts((1 < 2.5).inspect)
puts((1 == 2.5).inspect)

i = 0
acc = []
while i < 20
  acc << (0.5 + 0.5)
  i += 1
end
puts acc.uniq.inspect
