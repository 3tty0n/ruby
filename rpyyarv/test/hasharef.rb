h = { 1 => :a, 2 => :b, "s" => :c, :k => :d }
p h[1]
p h[2]
p h["s"]
p h[:k]
p h[99]
p h.fetch(1)
d = Hash.new(:default)
d[1] = :x
p d[1]
p d[2]
# A default_proc block stored in a CRuby Hash is a separate, known gap.
pr = Hash.new
pr[1] = :y
p pr[1]
n = Hash.new
p n[:missing]
frozen = { a: 1 }.freeze
p frozen[:a]
sub = Class.new(Hash).new
sub[:q] = 1
p sub[:q]
class Hash
  alias_method :orig_aref, :[]
  def [](k) = "redefined-#{orig_aref(k)}"
end
p({ z: 9 }[:z])
p "abc".to_s
s = +"m"
p s.to_s.equal?(s)
class MyS < String; end
m = MyS.new("q")
p m.to_s.class
p m.to_s == "q"
class String
  def to_s = "redefined-to_s"
end
p "abc".to_s
