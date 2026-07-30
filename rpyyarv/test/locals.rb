# Loader fixture: several locals, so the EP-relative index has to
# reach the right Frame.locals slot.
def f(a, b)
  c = a - b
  c
end

f(9, 4)
