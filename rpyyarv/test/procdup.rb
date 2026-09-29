# A dup shares the ifunc, so the original Proc a block memoised can die first.
def mkdup(&b) = b.dup
prs = (0...200).map { |i| mkdup { |x| GC.start if i % 50 == 0; x + i } }
GC.start
s = 0
prs.each { |pr| s += pr.call(1) }
p s
