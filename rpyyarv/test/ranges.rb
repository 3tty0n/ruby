r = []
("A".."E").each { |c| r << c }
p r
r = []
("a".."e").each { |c| r << c }
p r
r = []
(1..5).each { |i| r << i }
p r
r = []
(1...5).each { |i| r << i }
p r
r = []
("aa".."ad").each { |s| r << s }
p r
p ("A".."E").to_a
p (1..3).map { |i| i * 2 }
begin
  (1.0..2.0).each { |x| p x }
rescue TypeError => e
  p :TypeError
end
p ("A".."E").each.class
p ("A".."C").each_with_index.to_a
n = 0
("A".."Z").each { |c| n += 1 }
p n
