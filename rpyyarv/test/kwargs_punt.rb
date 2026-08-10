# The keyword shapes RPyYARV still hands back to CRuby. Deliberately kept out
# of the Makefile's gccheck list: its punt gate fails a punted file by design.
#
#   1. **splat at a call site (VM_CALL_KW_SPLAT, and the splatkw instruction)
#   2. keywords passed to super
#   3. keywords passed to yield / invokeblock
#   4. more than 31 keyword parameters, whose unspecified mask is a Hash
#
# Each is refused when the ISeq loads, so the whole file falls back to CRuby.

def kw(a: 1, b: 2)
  [a, b]
end

# 1
h = { a: 5 }
p kw(**h)

# 2
class Base
  def go(a: 1)
    a
  end
end

class Sub < Base
  def go(a: 1)
    super(a: a + 1)
  end
end

p Sub.new.go(a: 1)

# 3
def yielder
  yield(a: 9)
end

p(yielder { |a: 0| a })

# 4
def wide(k00: 0, k01: 0, k02: 0, k03: 0, k04: 0, k05: 0, k06: 0, k07: 0,
         k08: 0, k09: 0, k10: 0, k11: 0, k12: 0, k13: 0, k14: 0, k15: 0,
         k16: 0, k17: 0, k18: 0, k19: 0, k20: 0, k21: 0, k22: 0, k23: 0,
         k24: 0, k25: 0, k26: 0, k27: 0, k28: 0, k29: 0, k30: 0, k31: 0)
  k00 + k31
end

p wide(k31: 1)
