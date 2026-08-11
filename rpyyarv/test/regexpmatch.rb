s = "12, 34, ..., 90"
p(s =~ /^(\d+), (\d+), \.\.\., (\d+)$/)
p(/(\d+)/ =~ "abc 42")
p("zzz" =~ /q/)

def m(str)
  str =~ /a(b+)c/ ? true : false
end
p m("xabbbcy")
p m("nope")

p("abc123xyz".sub(/([a-z]+)(\d+)([a-z]+)/) { [$1, $2, $3, $&, $`, $', $+].join("|") })
x = "b+"
p(/a#{x}c/ =~ "abbbc")

# concatarray / concattoarray
b = [1, 2]
p [0, *b, 3]
c = [*b, *b]
p c
p [*(1..3), *b]
def all(*a) = a
h = { k: 1 }
p all(*b, 7, **h)

# opt_duparray_send
x = 3
p [1, 2, 3].include?(x)
p %w[a b].include?("c")
