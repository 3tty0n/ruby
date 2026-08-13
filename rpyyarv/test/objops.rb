# instance_of?/class/frozen?/key?/===/map/find_index fast paths against CRuby.

class Animal; end
class Dog < Animal; end

d = Dog.new
puts d.instance_of?(Dog)
puts d.instance_of?(Animal)
puts "s".instance_of?(String)
puts "s".instance_of?(Integer)
puts 1.instance_of?(Integer)
begin
  d.instance_of?("not a class")
rescue TypeError => e
  puts "type: #{e.class}"
end

puts d.class
puts "s".class
puts 42.class
puts nil.class
o = Object.new
def o.shout; end
puts o.class

s = "mutable"
puts s.frozen?
s.freeze
puts s.frozen?
puts :sym.frozen?
puts d.frozen?

h = { "a" => 1, "b" => nil, sym: 3 }
puts h.key?("a")
puts h.key?("b")
puts h.key?("missing")
puts h.has_key?(:sym)
dh = Hash.new { |hash, k| hash[k] = "made" }
puts dh.key?("x")
dh["x"]
puts dh.key?("x")

class MyHash < Hash
  def key?(k)
    "custom-#{k}"
  end
end
mh = MyHash.new
puts mh.key?("q")

puts "abc" === "abc"
puts "abc" === "abd"
puts "abc" === 42
puts String === "abc"
puts Animal === d
puts Comparable === 1
puts Integer === "no"
v = case d
    when String then "string"
    when Animal then "animal"
    else "other"
    end
puts v

puts [1, 2, 3].map { |x| x * 10 }.inspect
puts [].map { |x| x }.inspect
puts [1, 2, 3].map { |x| break "stopped" if x == 2; x }.inspect
puts %w[a b c].find_index { |x| x == "b" }
puts %w[a b c].find_index { |x| x == "z" }.inspect
puts %w[a b c].find_index("c")
puts [10, 20].map.class
puts %w[a].find_index.class
scopes = [{ "x" => 1 }, { "y" => 2 }]
puts scopes.find_index { |sc| sc.key?("y") }

require "set"
st = Set.new(%w[red green])
puts st.include?("red")
puts st.include?("blue")
puts [1, 2].include?(2)

puts "hello world".start_with?("hello")
puts "hello".start_with?("hello world")
puts "hello".start_with?("h", "x")

hs = { "k" => 1 }
puts hs["k"]
puts hs["absent"].inspect
hd = Hash.new("fallback")
puts hd["absent"]
hp = Hash.new { |hash, k| "made-#{k}" }
puts hp["absent"]
hs["w"] = 9
puts hs["w"]
begin
  {}.freeze["x"] = 1
rescue FrozenError => e
  puts "aset: #{e.class}"
end

acc = +"ascii"
acc << "-more"
utf = "héllo"
bin = "raw".b
bin << "bytes"
puts bin
mixed = +""
mixed << utf
puts mixed
begin
  ("frozen".freeze) << "x"
rescue FrozenError => e
  puts "push: #{e.class}"
end
