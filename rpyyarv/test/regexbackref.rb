
# =~ hit: position, Regexp.last_match, $~, $1
p("hello world" =~ /wor(ld)/)
p Regexp.last_match
p Regexp.last_match(1)
p($~ && $~[0])
p $1

# =~ miss clears the backref
p("hello world" =~ /zzz/)
p Regexp.last_match
p $~

# Regexp#=~ with the operands swapped
p(/wor(ld)/ =~ "hello world")
p Regexp.last_match(1)

# === hit/miss, then last_match
case "HELLO"
when /^[A-Z]+$/ then p :upper
else p :other
end
p Regexp.last_match
p(/^[A-Z]+$/ === "hello")
p Regexp.last_match

# last_match(n) for n = 0, 1, 2, 99, and negative
"c(a)t" =~ /c(.)t/ rescue nil
"cat" =~ /c(.)t/
p Regexp.last_match(0)
p Regexp.last_match(1)
p Regexp.last_match(2)
p Regexp.last_match(99)
p Regexp.last_match(-1)

# named-group regexp reached through a Fixnum index
"var = val" =~ /(?<lhs>\w+)\s*=\s*(?<rhs>\w+)/
p Regexp.last_match(1)
p Regexp.last_match(2)
p Regexp.last_match(:lhs)

# gsub/sub still set the backref the same way they always did
p "hello world".gsub(/o/, "0")
p Regexp.last_match
s2 = +"hello world"
p s2.sub!(/o/, "0")
p Regexp.last_match(0)
p "no match here".sub(/zzz/, "0")
p Regexp.last_match

# match() returns a MatchData whose captures work
md = "hello world".match(/wor(ld)/)
p md[0]
p md[1]
p "hello world".match(/zzz/)

# the shop_filter shape
def shop_filter(str)
  str =~ /(\w+): (\w+)/ ? [Regexp.last_match(1), Regexp.last_match(2)] : nil
end
p shop_filter("key: value")
p shop_filter("no match")

# fallback: String subclass receiver
class MyStr < String; end
p(MyStr.new("hello world") =~ /wor(ld)/)
p Regexp.last_match(1)

# fallback: monkeypatched =~
class String
  alias_method :orig_eq_tilde, :=~
  def =~(other)
    :patched
  end
end
p("hello" =~ /h/)
class String
  remove_method :=~
  alias_method :=~, :orig_eq_tilde
end

# fallback: Regexp subclass
class MyRe < Regexp; end
p(MyRe.new("wor(ld)") =~ "hello world")
p Regexp.last_match(1)
