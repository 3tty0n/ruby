# A throw crossing libruby's frames parks its own data in errinfo; nothing on
# the way out may read that as an exception.

def deep(n)
  throw(:t, n) if n == 0
  [n].each { |x| deep(x - 1) }
  :never
end
p catch(:t) { deep(4) }

p catch(:t) { "abc".gsub(/b/) { throw :t, :from_gsub } }
p catch(:t) { { a: 1, b: 2 }.each { |k, _| throw :t, k } }
p catch(:t) { [1, 2].map { |x| x == 2 ? throw(:t, :m) : x } }
p catch(:t) { [3, 4].each_with_object([]) { |x, a| throw :t, a if x == 4 } }

r = catch(:outer) do
  catch(:inner) { throw :outer, :jumped }
  :no
end
p r

begin
  catch(:t) { raise 'inner' }
rescue => e
  p e.message
end

p catch(:t) {
  begin
    throw :t, :ensured
  ensure
    $stdout.write('')
  end
}
