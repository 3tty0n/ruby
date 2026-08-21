# Range#include?/cover?/member?/=== over Integers is r_cover_p, and every
# other shape still goes to CRuby.
r = (1..5)
x = (1...5)
puts [r.include?(0), r.include?(1), r.include?(5), r.include?(6)].inspect
puts [x.include?(0), x.include?(1), x.include?(4), x.include?(5)].inspect
puts [r.cover?(3), x.cover?(5), r.member?(2), r === 4, x === 5].inspect
puts [(-3..3).include?(-3), (-3..3).include?(-4), (5..1).include?(3)].inspect
puts [(1..1).include?(1), (1...1).include?(1)].inspect
puts [r.include?(2.5), r.include?("3"), r.include?(nil)].inspect
puts [(1.0..5.0).include?(3), ('a'..'e').include?('c')].inspect
puts [(1..).include?(9999), (..5).include?(-9999)].inspect
puts [(1..5).to_a.include?(3), [1, 2].include?(2)].inspect
big = 1 << 70
puts [(1..big).include?(5), (1..5).include?(big)].inspect
case 3
when 1..2 then puts 'no'
when 3..4 then puts 'yes'
end
class Range
  alias_method :orig_include?, :include?
  def include?(v) = 'redefined'
end
puts (1..5).include?(3)
class Range
  remove_method :include?
  alias_method :include?, :orig_include?
end
puts (1..5).include?(3)
