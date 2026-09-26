# A redefined Integer#+ must not change how many times a core iterator
# yields: CRuby's Integer#times counts with succ and Array#each is C.
class Integer
  alias_method :__orig_plus, :+
  def +(o) = __orig_plus(o).__orig_plus(100)
end
n = 0; 10.times { n = n.__orig_plus(1) }
m = 0; [1, 2, 3, 4, 5].each { m = m.__orig_plus(1) }
class Integer; alias_method :+, :__orig_plus; end
p n, m
