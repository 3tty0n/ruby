# public_send resolves like send but keeps the callee public.
class P
  def pub(a = 1) = "pub#{a}"
  private def priv = :priv
  protected def prot = :prot
  def call_prot(o) = o.prot
  def kw(a:, b: 2) = [a, b]
  def splat(*a, **k) = [a, k]
end
o = P.new
p o.public_send(:pub)
p o.public_send(:pub, 9)
p o.public_send("pub", 9)
p o.public_send(:kw, a: 1)
p o.public_send(:splat, 1, 2, x: 3)
p o.public_send(:splat, *[1, 2], **{x: 3})
begin
  o.public_send(:priv)
rescue NoMethodError => e
  puts "priv: #{e.class}"
end
begin
  o.public_send(:prot)
rescue NoMethodError => e
  puts "prot: #{e.class}"
end
p o.send(:priv)
p o.__send__(:priv)
p o.send(:public_send, :pub)
begin
  o.public_send(:nope)
rescue NoMethodError => e
  puts "nope: #{e.class}"
end
p [1, 2, 3].public_send(:map) { |x| x * 2 }
p o.public_send(:pub, 3)
# freeze / to_sym / to_a / negative?
s = "x".dup
p s.freeze.frozen?, s.frozen?
a = [1, 2]
p a.freeze.frozen?, a.to_a.equal?(a)
h = {a: 1}
p h.freeze.frozen?
obj = Object.new
p obj.freeze.equal?(obj), obj.frozen?
p :sym.to_sym, "str".to_sym, :sym.to_sym.equal?(:sym)
p 1.negative?, (-1).negative?, 0.negative?, (-(2**70)).negative?, (2**70).negative?
p 1.0.negative?, (-1.5).negative?
p nil.freeze, 1.freeze, :s.freeze
class MyArr < Array; end
m = MyArr.new([1,2])
p m.to_a.class, m.to_a == [1,2]
class Neg; def negative? = :custom; end
p Neg.new.negative?
