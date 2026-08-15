# StringScanner's struct-read fast paths against the real strscan.
require "strscan"

s = StringScanner.new("hello world foo")
p s.pos
p s.eos?
p s.skip(/hello/)
p s.pos
p s.matched_size
p s.skip(/hello/)
p s.matched_size
p s.skip(/\s+/)
p s.skip(/\w+/)
p s.pos
s.pos = 0
p s.pos
s.pos = -3
p s.pos
begin
  s.pos = 99
rescue RangeError
  puts "RangeError"
end
p s.eos?
s.pos = 15
p s.eos?

f = StringScanner.new("abc abc", fixed_anchor: true)
p f.skip(/abc/)
p f.pos
p f.matched_size
p f.skip(/\s/)
p f.skip(/abc/)
p f.pos

b = "hello world"
p b.byteslice(0, 5)
p b.byteslice(6, 99)
p b.byteslice(-5, 2)
p b.byteslice(3, -1)
p b.byteslice(11, 0)
p b.byteslice(12, 1)
