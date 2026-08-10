def all(*a) = a

b = [1, 2]
p all(*b, 3)
p all(*b, 3, 4)
p all(*[], 3)
p [*b, 3, 4]

# The Array pushtoarray appends to is the fresh one splatarray made, so the
# source must be untouched.
src = [1, 2]
p [*src, 9]
p src

p [1, 2, 3].values_at(*b, 0)
