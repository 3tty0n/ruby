# Range#each never materialises an Integer range: an endless one has no array
# and a Float end only bounds the walk (range.c), so both must stream.
def finite; (2..10).each { |i| return i if i == 4 }; :fell; end
def endless; (2..).each { |i| return i if i == 4 }; :fell; end
def floaty; (2..Float::INFINITY).each { |i| return i if i == 5 }; :fell; end
puts [finite, endless, floaty].inspect

a = []
(1..4).each { |i| a << i }
(1...4).each { |i| a << i }
(1..3.5).each { |i| a << i }
(1...3.5).each { |i| a << i }
(5..1).each { |i| a << i }
puts a.inspect

n = 0
(1..).each { |i| n += i; break if i == 5 }
puts n

puts (1..4).each.to_a.inspect
puts ('a'..'e').each.to_a.inspect
b = []
('a'..'d').each { |s| b << s }
puts b.inspect
puts (1..0).each { |i| }.inspect

# The uniquifier idiom rubocop-ast uses for constant names.
module Sx; Y = 1; Y_2 = 1; Y_3 = 1; Z_2 = 1; end
def uniq(base)
  return base unless Sx.const_defined?(base)
  (2..Float::INFINITY).each do |i|
    u = "#{base}_#{i}"
    return u unless Sx.const_defined?(u)
  end
end
puts [uniq("Y"), uniq("Z"), uniq("Q")].inspect
