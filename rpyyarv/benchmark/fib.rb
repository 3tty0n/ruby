# Call-heavy recursion: fib(30), repeated so CRuby lands in the target range.
def fib(n)
  if n < 2
    n
  else
    fib(n - 1) + fib(n - 2)
  end
end

r = 0
s = 0
while r < 18
  s = s + fib(30)
  r = r + 1
end
puts s
