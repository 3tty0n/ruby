# Recursion depths that only fit once rpy_stacktoobig.stack_length is raised
# past MAX_STACK_SIZE; the block form interposes a CRuby frame per level.

def down(n)
  return 0 if n == 0
  1 + down(n - 1)
end

def down_block(n)
  return 0 if n == 0
  r = 0
  [1].each { r = 1 + down_block(n - 1) }
  r
end

def sum_to(n)
  return 0 if n == 0
  n + sum_to(n - 1)
end

[1, 100, 1000, 2500, 3500].each do |d|
  puts down(d)
end

[1, 100, 900, 1500].each do |d|
  puts down_block(d)
end

puts sum_to(3000)

# Back at the top: an unwound deep call must leave the shim nesting where it
# started, or the next one reuses a live status slot.
puts down(2500)
puts down_block(900)
