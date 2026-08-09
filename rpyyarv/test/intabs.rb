# Integer#abs on the native path, and every receiver that must fall back.

[0, 1, -1, 7, -7, 1073741823, -1073741824,
 4611686018427387903, -4611686018427387903].each do |n|
  puts n.abs
end

# The fixnum minimum negates to a Bignum, which only CRuby builds.
puts((-4611686018427387904).abs)
puts((2**62).abs)
puts((-2**62).abs)
puts((-2**200).abs)
puts((2**200).abs)

puts(-3.5.abs)
puts((-3.5).abs)
puts(0.0.abs)
puts((-0.0).abs)

x = -5
puts x.abs
puts x.abs.abs
puts (0 - x.abs)

class Integer
  def abs
    "redefined"
  end
end

puts(-9.abs)
puts 9.abs
puts((-2**200).abs)
