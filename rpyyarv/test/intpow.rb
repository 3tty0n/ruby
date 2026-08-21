# Integer ** Integer stays exact in a word on the fast path; every other
# shape (negative exponent, bignum result, Float) still goes to CRuby.
puts [2**0, 2**1, 2**10, 3**5, (-2)**3, (-2)**4, 0**0, 1**100].inspect
puts [2**62, 2**63, 2**64, 10**18, 10**19, 10**30].inspect
puts [(2**-1), (2**-2), 0**-1].inspect rescue puts $!.class
puts [2.0**3, 2**3.0, 2**0.5].inspect
puts [(1 << 70)**2, 2**(1 << 3)].inspect
puts [(-3)**7, (-1)**101, (-1)**100].inspect
puts (2**100).class
class Integer
  alias_method :orig_pow, :**
  def **(o) = 'redefined'
end
puts 2**3
class Integer
  remove_method :**
  alias_method :**, :orig_pow
end
puts 2**3
