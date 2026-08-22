# rb_iter_break from CRuby's own block has to end the method it was yielded
# from: yielding to a proc-ized copy leaves vm_throw with no target frame.
def m; yield 1; yield 2; yield 3; :ret; end
puts to_enum(:m).take(2).inspect
puts to_enum(:m).take(9).inspect
puts to_enum(:m).first.inspect
puts to_enum(:m).first(2).inspect
puts to_enum(:m).include?(2).inspect
puts to_enum(:m).find { |x| x == 2 }.inspect
puts to_enum(:m).to_a.inspect
puts to_enum(:m).lazy.first(2).inspect
puts to_enum(:m).each_slice(2).to_a.inspect
puts to_enum(:m).count.inspect

# Our own block breaking out of our own method still works.
puts(m { |x| break x * 10 }.inspect)
# A block that raises still raises.
begin
  m { |x| raise ArgumentError, "boom" if x == 2 }
rescue ArgumentError => e
  puts e.message
end
# ensure runs when CRuby's block breaks the method.
def ens
  yield 1
  yield 2
  :done
ensure
  puts "ensure ran"
end
puts to_enum(:ens).first.inspect

# Nested: our method yields from inside a CRuby iterator.
def nest
  [1, 2, 3].each { |x| yield x }
  :nested
end
puts to_enum(:nest).first(2).inspect
puts to_enum(:nest).to_a.inspect

# A method taking an explicit block parameter.
def blk(&b); b.call(1); b.call(2); :blk; end
puts to_enum(:blk).first.inspect

# &b handed to a CFUNC: rb_iter_break unwinds to a frame past our own, so the
# tag rides out of rb_protect instead of being read as an exception.
def pass(&b)
  return to_enum(:pass) unless b
  [1, 2, 3].reverse_each(&b)
  :passed
end
puts to_enum(:pass).first.inspect
puts to_enum(:pass).first(2).inspect
puts to_enum(:pass).to_a.inspect
puts to_enum(:pass).find { |x| x == 2 }.inspect
puts(pass { |x| x }.inspect)
puts(pass { |x| break x }.inspect)

def entry(&b)
  return to_enum(:entry) unless b
  [1, 2, 3].each_entry(&b)
  :entered
end
puts to_enum(:entry).first.inspect
puts to_enum(:entry).to_a.inspect

# The same shape one method deeper, and with an ensure to run on the way out.
def outer(&b)
  return to_enum(:outer) unless b
  pass(&b)
ensure
  puts 'outer ensure'
end
puts to_enum(:outer).first.inspect
