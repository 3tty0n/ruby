# define_method's block IS the method body: `return` leaves the method, and
# that has to hold when CRuby is the caller (public_send, Method#call, an
# iterator), not only when RPyYARV dispatches the call itself.
class C
  [:a, :b].each do |t|
    define_method(:"on_#{t}") do |node|
      return :early if node == 1
      :late
    end
  end
  define_method(:two) do |x, y|
    return :both if x && y
    :one
  end
end
c = C.new
puts [c.on_a(1), c.on_a(2), c.on_b(1)].inspect
puts [c.public_send(:on_a, 1), c.send(:on_a, 1)].inspect
puts c.method(:on_a).call(1).inspect
puts [1, 2].map { |n| c.public_send(:on_a, n) }.inspect
puts [1, 2].flat_map { |n| [c.public_send(:on_a, n)] }.inspect
puts C.instance_method(:on_a).bind(c).call(1).inspect
puts [c.two(true, true), c.two(true, false)].inspect

# Arity is method-style, not block-style.
begin
  c.public_send(:two, 1)
rescue ArgumentError => e
  puts "ArgumentError"
end

# A plain block still keeps block semantics.
def takes; yield 1; :after; end
puts takes { |x| x * 2 }.inspect
puts [[1, 2]].map { |a, b| [a, b] }.inspect

# ensure inside a bmethod runs on the early return.
class D
  define_method(:guarded) do |x|
    return :out if x
    :in
  ensure
    $ran = true
  end
end
$ran = false
puts [D.new.public_send(:guarded, true), $ran].inspect
