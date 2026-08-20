# Array#rotate! and the three-argument Array#[]=: the fast paths must agree
# with CRuby on the odd cases they hand back, not only on the hot one.

a = [0, 1, 2, 3, 4, 5, 6, 7]
puts a.dup.rotate!(3).inspect
puts a.dup.rotate!(-3).inspect
puts a.dup.rotate!(0).inspect
puts a.dup.rotate!(8).inspect
puts a.dup.rotate!(-8).inspect
puts a.dup.rotate!(19).inspect
puts a.dup.rotate!(-19).inspect
puts [].rotate!(3).inspect
puts [7].rotate!(3).inspect
puts [:a, "b", 2.5, nil].rotate!(1).inspect

r = a.dup
puts r.rotate!(2).equal?(r)

begin
  [1, 2, 3].freeze.rotate!(1)
rescue => e
  puts e.class
end

class Sub < Array; end
puts Sub.new([1, 2, 3]).rotate!(1).inspect

b = [0, 1, 2, 3, 4, 5, 6, 7]
b[2, 3] = [8, 9, 10]
puts b.inspect
b[0, 8] = [1, 1, 1, 1, 1, 1, 1, 1]
puts b.inspect
puts (b[1, 2] = [4, 5]).inspect

c = [0, 1, 2, 3]
c[1, 2] = [9]
puts c.inspect
c = [0, 1, 2, 3]
c[1, 1] = [7, 7, 7]
puts c.inspect
c = [0, 1, 2, 3]
c[1, 2] = 5
puts c.inspect
c = [0, 1, 2, 3]
c[-2, 2] = [8, 8]
puts c.inspect
c = [0, 1, 2, 3]
c[2, 6] = [1, 2]
puts c.inspect
c = [0, 1, 2, 3]
c[6, 1] = [1]
puts c.inspect
c = [0, 1, 2, 3]
c[1, 0] = []
puts c.inspect

d = [nil, nil, nil]
d[0, 3] = ["x", :y, 1 << 70]
puts d.inspect

e = [1, 2, 3]
e[0, 3] = e.dup
puts e.inspect

begin
  [1, 2, 3].freeze[0, 3] = [4, 5, 6]
rescue => err
  puts err.class
end

begin
  [1, 2, 3][0, -1] = [4]
rescue => err
  puts err.class
end
