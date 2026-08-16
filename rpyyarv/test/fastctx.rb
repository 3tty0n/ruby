# The native fast paths for plain Array/Hash boundary sends (liquid Context#initialize).
h = { a: 1, b: 2 }
p h.keys
p({}.keys)
p h.key?(:a)
p h.key?(:z)
p h.has_key?(:b)
p h.key?("a")

a1 = [1, [2, 3], 4]
p a1.flatten!
p a1
a2 = [1, 2, 3]
p a2.flatten!
p a2
a3 = [1, [2, [3, 4]], 5]
p a3.flatten!
p a3

a4 = [1, 2].freeze
p a4.frozen?
p a4.equal?(a4.freeze)
h2 = { a: 1 }.freeze
p h2.frozen?

a5 = [1, 2, 3]
p a5.shift
p a5
p [].shift
a6 = [2, 3]
p a6.unshift(1)
p a6

frozen_ary = [1, 2].freeze
begin
  frozen_ary.shift
rescue FrozenError => e
  puts e.class
end
begin
  frozen_ary.unshift(0)
rescue FrozenError => e
  puts e.class
end
begin
  frozen_ary.flatten!
rescue FrozenError => e
  puts e.class
end

class MyArray < Array
end
ma = MyArray.new([1, [2, 3]])
p ma.flatten!
p ma.shift
ma.unshift(9)
p ma

class MyHash < Hash
end
mh = MyHash.new
mh[:a] = 1
p mh.keys

class Array
  alias_method :orig_shift, :shift
  def shift
    "patched:" + orig_shift.to_s
  end
end
p [1, 2].shift
