# Interception fixture.
#
# The marker below is built at run time, so it can never appear in a dump of
# this file's ISeq -- only in the output of a real execution. `make check`
# greps for it to prove CRuby did not run the script.
def fib(n)
  a, b = 0, 1
  while n > 0
    a, b = b, a + b
    n -= 1
  end
  a
end

puts "EXECUTED:#{fib(30)}"
