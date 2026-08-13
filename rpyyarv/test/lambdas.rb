# Lambda semantics: strict arity, own return, arity/lambda? introspection.

add = ->(a, b) { a + b }
puts add.call(1, 2)
puts add.(3, 4)
puts add[5, 6]

# Strict arity, and no autosplat of a single Array argument.
begin
  add.call(1)
rescue ArgumentError => e
  puts "few: #{e.class}"
end
begin
  add.call(1, 2, 3)
rescue ArgumentError => e
  puts "many: #{e.class}"
end
begin
  add.call([1, 2])
rescue ArgumentError => e
  puts "nosplat: #{e.class}"
end
puts proc { |a, b| "#{a}/#{b}" }.call([1, 2])

# arity over the parameter shapes, lambda and proc alike.
puts -> {}.arity
puts ->(a) {}.arity
puts ->(a, b) {}.arity
puts ->(a, b = 1) {}.arity
puts ->(a, *r) {}.arity
puts ->(a, b: 2) {}.arity
puts ->(a, b:) {}.arity
puts ->(**kw) {}.arity
puts proc {}.arity
puts proc { |a, b| }.arity
puts proc { |a, *r| }.arity
puts add.lambda?
puts proc { |x| x }.lambda?

# Optional, rest and keyword parameters through a lambda call.
sig = ->(a, b = 10, *r, k: 0) { "#{a} #{b} #{r.inspect} #{k}" }
puts sig.call(1)
puts sig.call(1, 2, 3, 4, k: 5)

# return leaves the lambda, not the enclosing method.
def ret_lambda
  f = -> { return 1 }
  f.call
  2
end
puts ret_lambda

# ...while return in a plain block still leaves the method.
def ret_block
  [1].each { return 3 }
  4
end
puts ret_block

# return inside a plain block written in a lambda stops at the lambda.
def ret_nested
  f = -> { [1].each { return 5 }; 6 }
  "#{f.call} 7"
end
puts ret_nested

# break and next in a lambda body both just answer the value.
puts -> { break 8 }.call
puts -> { next 9 }.call

# A lambda outlives its defining frame with its captures intact.
def make_counter
  n = 0
  -> { n += 1 }
end
c = make_counter
c.call
puts c.call

# Yielding to a lambda passed as the block is strict too.
def yield_one
  yield 1
end
begin
  yield_one(&->(a, b) { a + b })
rescue ArgumentError => e
  puts "yield: #{e.class}"
end
puts yield_one(&->(a) { a * 10 })

# Proc#=== runs the lambda; case/when dispatches through it.
even = ->(n) { n.even? }
puts even === 4
puts(case 3 when even then "even" else "odd" end)

s = ->(x) { x.to_s }
puts [10, 20].map(&s).join(",")

# Kernel#lambda and Kernel#proc with a literal block.
g = lambda { |a| a * 2 }
puts g.call(21)
puts g.lambda?
begin
  g.call
rescue ArgumentError => e
  puts "klambda: #{e.class}"
end
h = proc { |a, b| [a, b].inspect }
puts h.call(1)
puts h.lambda?
