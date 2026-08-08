# Pure Float arithmetic, no sends: the flonum encode/decode overhead probe.
n = 10000000
i = 0
s = 0.0
while i < n
  s = s + i * 0.5 - 0.25
  s = s * 0.999999 if s > 1.0e9
  i = i + 1
end
puts s
