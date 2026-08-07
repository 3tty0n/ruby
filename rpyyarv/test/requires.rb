require_relative 'requires_lib'

puts require_relative('requires_lib')

c = LibCounter.new
sum = 0
i = 0
while i < 1000
  sum = lib_add(sum, c.bump(i))
  i = i + 1
end
puts sum
