# The opcodes added alongside exceptions, checked against CRuby by diff.

p 12 & 10, 12 | 10, 0 & 1, -1 & 255
p true & false, true | false, nil | 3, nil & 3

h = {}
p h.size
h2 = {1 => "a", :b => 2, "c" => [3]}
p h2[1], h2[:b], h2["c"]
lit = {4 => 5, 6 => 7}
copy = lit.dup
copy[4] = 99
p lit[4], copy[4]

a = [1, 2, 3]
x, y, z = *a
p x, y, z
b = *a
p b
c = *4
p c

p Math::PI
p ::Integer
p Float::INFINITY

class Outer
  class Inner
    VALUE = 42
  end
end
p Outer::Inner::VALUE

total = 0
1.step(10, 3) { |i| total = total + i }
p total
down = []
9.step(1, -4) { |i| down << i }
p down

class Aliased
  def greet
    "hello"
  end
  alias hi greet
end
p Aliased.new.hi

alias puts_orig puts
def puts(x)
  puts_orig "wrapped #{x}"
end
puts "one"
undef puts
alias puts puts_orig
puts "two"
