# &:sym is a public send; RPyYARV runs one it owns without crossing to CRuby.
class R
  attr_reader :n
  def initialize(n) = @n = n
  def big? = n > 2
  def plus(k) = n + k
  private def hidden = :no
  protected def prot = :nope
  def to_s = "R#{n}"
end
rs = [R.new(1), R.new(2), R.new(3)]
p rs.map(&:n)
p rs.select(&:big?).map(&:n)
p rs.map(&:to_s)
p rs.each_with_object([]) { |r, a| a << r.n }
p rs.sum(&:n)
p rs.sort_by(&:n).map(&:n)
p rs.group_by(&:big?).transform_values { |v| v.map(&:n) }
begin
  rs.map(&:hidden)
rescue NoMethodError => e
  puts e.class
end
begin
  rs.map(&:prot)
rescue NoMethodError => e
  puts e.class
end
begin
  rs.map(&:plus)
rescue ArgumentError => e
  puts e.class
end
p [[1, 2], [3, 4]].map(&:first)
p %w[a b].map(&:upcase)
p rs.map(&:frozen?)
# a &:sym block that raises still raises out of the CFUNC
begin
  [R.new(0), nil].map(&:big?)
rescue NoMethodError => e
  puts e.class
end
# subclass overriding
class S2 < R
  def big? = false
end
p [S2.new(9)].select(&:big?)
p rs.map(&:n).map(&:to_s)
# A &:sym block handed to a method CRuby owns: it has no ISeq and no frame.
p [[1, 2], [3, 4]].flat_map(&:first)
p({ :a => 1 }.any?(&:frozen?))
p rs.min_by(&:n).n
