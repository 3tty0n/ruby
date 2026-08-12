# CRuby calling back into an RPyYARV method: the keyword flag has to survive.
def outer(x, flag: false) = [x, flag]
m = method(:outer)
p m.call(1, flag: true)
p m.call(1)
p m.(2, flag: false)
p [[1], [2]].map { |a| m.call(a.first, flag: true) }

class K
  def kw(a, b: 1, c: 2) = [a, b, c]
  def only_kw(x:) = x
  def splat(*a, **k) = [a, k]
  def opt(a, b = 5, c: 3) = [a, b, c]
end
k = K.new
p K.instance_method(:kw).bind_call(k, 1, b: 9)
p k.method(:kw).call(1, c: 9)
p k.method(:only_kw).call(x: 4)
p k.method(:splat).call(1, 2, z: 3)
p k.method(:opt).call(1)
p k.method(:opt).call(1, 2, c: 9)
p k.public_send(:kw, 1, b: 7)
h = { b: 8 }
p k.method(:kw).call(1, **h)
begin
  k.method(:only_kw).call(4)
rescue ArgumentError
  p :ArgumentError
end
p [1, 2].map(&k.method(:kw))
