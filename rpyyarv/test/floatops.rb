# ---- Float#to_i in a hot loop, over both flonums and heap Floats ----

def trunc(x)
  x.to_i
end

up = 0
down = 0
tiny = 0
i = 0
while i < 400
  up += trunc(i * 1.5)
  down += trunc(-(i * 1.5))
  tiny += trunc(1e-300)
  i += 1
end
puts up
puts down
puts tiny

puts trunc(3.7)
puts trunc(3.2)
puts trunc(-3.7)
puts trunc(-3.2)
puts trunc(0.0)
puts trunc(-0.0)
puts trunc(0.5)
puts trunc(-0.5)
puts trunc(1e-300)
puts trunc(-1e-300)
puts trunc(3.7).class

# ---- NaN and the two infinities ----

nan = 0.0 / 0.0
inf = 1.0 / 0.0

def guarded(x)
  x.to_i
rescue FloatDomainError => e
  "FloatDomainError #{e.message}"
end

i = 0
while i < 400
  guarded(nan)
  guarded(inf)
  guarded(-inf)
  i += 1
end
puts guarded(nan)
puts guarded(inf)
puts guarded(-inf)

# ---- either side of the fixnum boundary ----

big = 2.0**62
small = -(2.0**62)
inside = (2**62 - 512).to_f
inside_neg = -inside

i = 0
while i < 400
  trunc(big)
  trunc(small)
  trunc(inside)
  trunc(inside_neg)
  i += 1
end
puts trunc(inside)
puts trunc(inside).class
puts trunc(inside_neg)
puts trunc(small)
puts trunc(small).class
puts trunc(big)
puts trunc(big).class
puts trunc(big * 4)
puts trunc(big * 4).class
puts trunc(-big * 4)
puts trunc(1e300)
puts trunc(1e300).class
puts trunc(-1e300).class

# ---- Float#-@ ----

def neg(x)
  -x
end

sum = 0.0
i = 0
while i < 400
  sum += neg(i * 0.5)
  sum += neg(neg(i * 0.25))
  i += 1
end
puts sum

puts neg(1.5)
puts neg(-1.5)
puts neg(0.0)
puts neg(-0.0)
puts (1.0 / neg(0.0))
puts (1.0 / neg(-0.0))
puts neg(nan).nan?
puts neg(inf)
puts neg(-inf)
puts neg(1.5).class

# A result no flonum can hold, so the heap Float path runs.
puts neg(1e300)
puts neg(-1e300)
puts neg(1e-300)
puts neg(1.7976931348623157e308)
puts neg(5.0e-324)
puts neg(2.0**62)
puts neg(neg(1e300))
GC.start
puts neg(1e300)

kept = []
i = 0
while i < 200
  kept << neg(1e300 + i)
  GC.start if i % 47 == 0
  i += 1
end
GC.start
puts kept.size
puts kept.first
puts kept.last

# ---- the neighbouring conversions must not move ----

puts 2.5.to_int
puts 2.5.truncate
puts 2.5.floor
puts (-2.5).floor

# ---- both redefined once the fast path is warm ----

class Float
  def to_i
    :redefined_to_i
  end

  def -@
    :redefined_uminus
  end
end

half = 1.5
i = 0
while i < 200
  half.to_i
  neg(half)
  i += 1
end
puts half.to_i.inspect
puts neg(half).inspect
puts neg(4.5).inspect
puts trunc(9.5).inspect
puts 2.5.to_int
