s = "a\0b" * 4
puts s.bytesize
puts s.unpack("C*").join(",")
t = "x" + 0.chr + "y"
puts (t * 3).bytesize
puts ("\0\0\0".b + "end").bytesize
