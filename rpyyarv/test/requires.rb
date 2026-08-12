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

# The provided path must survive a GC: rb_provide would leave a dangling fstring here.
feature = $LOADED_FEATURES.find {|f| f.end_with?('requires_lib.rb') }
GC.start
puts feature.end_with?('requires_lib.rb')

# a, b = nil expands as vm_expandarray does, not as an Array.
a, b = nil
p [a, b]
a, b = 7
p [a, b]
