# The native fast paths for mail's hottest boundary sends.
p "Hello".casecmp("hello")
p "abc".casecmp("ABD")
p "ABC".casecmp("ab")
p "abc".casecmp(1)
p "Hello".downcase
p (+"hello").downcase!
s = +"HeLLo"
p s.downcase!
p s
p "hello".upcase
p (+"HELLO").upcase!
p :sym.to_s
p :sym.to_s.frozen?
s2 = +"orig"
d = s2.dup
d << "x"
p [s2, d]
p(1 <=> 2)
p(2 <=> 2)
p(3 <=> 2)
p(1 <=> "a")
p("a" <=> "b")
p 7.div(2)
p(-7.div(2))
p 7.div(-2)
p 1234567890.div(37)

class MyList < Array
end

l = MyList.new
l.push(1, 2, 3)
p l[1]
p l[-1]
p l[9]
p l.length
p l.size
p l.select { |x| x > 1 }
p l.select { |x| x > 1 }.class

class CmpBox
  include Comparable
  attr_reader :v

  def initialize(v)
    @v = v
  end

  def <=>(other)
    v <=> other.v
  end
end

a = CmpBox.new(1)
b = CmpBox.new(2)
p a < b
p a > b
p a <= b
p b >= a
begin
  CmpBox.new(1) < 2
rescue ArgumentError, NoMethodError => e
  puts e.class
end

p Encoding.find("UTF-8").name
p Encoding.find("utf-8").name
begin
  Encoding.find("nope-enc")
rescue ArgumentError
  puts "ArgumentError"
end

p "foo_bar_baz".tr("_", "-")
p "hello".tr("l", "L")
p "hello".tr("a-y", "b-z")
p "hello world".index("wor")
p "hello".index("zz")
p "hello".index("")
p "hello".length
p "hello".size
p "こんにちは".length

p "hello".match?(/l+/)
p "hello".match?(/z/)
p "".empty?
p "x".empty?
p({}.empty?)
p({ a: 1 }.empty?)
f = -"frozen me"
p f.frozen?
p((-"a").equal?(-"a"))
arr = [1, 2, 3]
p arr.pop
p arr
p arr.push(9)
p [].pop
begin
  "x".match?(/x/.tap { Regexp })
rescue StandardError
  puts "err"
end

p 0.to_s
p 42.to_s
p(-7.to_s)

p "hello world".gsub(/o/, "0")
p "hello world".gsub("o", "0")
s3 = +"hello world"
p s3.gsub!(/o/, "0")
p s3
p (+"no match").gsub!(/z/, "0")
p "a.b.c".gsub(".", "-")
p "keep \\0 literal".gsub("l", "\\0")
p "abc".gsub(/b/) { "X" }

class MyString < String
end
p MyString.new("hello").gsub(/l/, "L")

class String
  alias_method :orig_gsub, :gsub
  def gsub(*args)
    "patched:" + orig_gsub(*args)
  end
end
p "hello".gsub("l", "L")
