# The keyword shapes RPyYARV still hands back to CRuby. Deliberately kept out
# of the Makefile's gccheck list: its gate fails a delegated file by design.
#
#   1. a ** under a &block, which puts an unimplemented splatkw between them
#   2. more than 31 keyword parameters, whose unspecified mask is a Hash
#
# Each is refused when the ISeq loads, so the whole file falls back to CRuby.

def kw(a: 1, b: 2)
  [a, b]
end

# 1
def blocky(&b)
  kw(**{ a: 5 }, &b)
end

p blocky { 1 }

# 2
def wide(k00: 0, k01: 0, k02: 0, k03: 0, k04: 0, k05: 0, k06: 0, k07: 0,
         k08: 0, k09: 0, k10: 0, k11: 0, k12: 0, k13: 0, k14: 0, k15: 0,
         k16: 0, k17: 0, k18: 0, k19: 0, k20: 0, k21: 0, k22: 0, k23: 0,
         k24: 0, k25: 0, k26: 0, k27: 0, k28: 0, k29: 0, k30: 0, k31: 0)
  k00 + k31
end

p wide(k31: 1)
