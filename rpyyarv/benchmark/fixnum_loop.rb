# Pure fixnum arithmetic, no sends: the tagging/unboxing overhead probe.
n = 50000000
i = 0
s = 0
while i < n
  s = s + i * 3 - 1
  i = i + 1
end
puts s
