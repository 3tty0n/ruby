def add(a, b)
  a + b
end

def fib(n)
  if n < 2
    n
  else
    fib(n - 1) + fib(n - 2)
  end
end

puts add(2, 3)
puts fib(10)
__END__
5
55
