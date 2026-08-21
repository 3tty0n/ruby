# Proc#parameters / Method#parameters: CRuby sees an RPyYARV def as a cfunc,
# so the answer has to come from the ISeq's own parameter table.
def take(&blk) = blk
puts take { |a, b, c| }.parameters.inspect
puts take { |a| }.parameters.inspect
puts take { }.parameters.inspect
puts take { |a, *r, k: 1, &b| }.parameters.inspect
puts take { |a, *, **, &| }.parameters.inspect
puts lambda { |a, b| }.parameters.inspect
puts proc { |x, y| }.parameters.inspect
puts ->(a, b = 2) {}.parameters.inspect
puts ->(a, b = 2, *c, d:, e: 3, **f, &g) {}.parameters.inspect
puts proc { |a, *b, c| }.parameters.inspect

def m0; end
def m1(a, b = 1, *c, d:, e: 2, **f, &g); end
def m2(a, (b, c), *rest); end
def m3(*); end
def m4(**); end
puts method(:m0).parameters.inspect
puts method(:m1).parameters.inspect
puts method(:m2).parameters.inspect
puts method(:m3).parameters.inspect
puts method(:m4).parameters.inspect

# A define_method block with only leading required parameters is ours; one
# with optionals or keywords stays CRuby's bmethod, which reports [[:rest]].
class C
  def self.cm(x, y = 1); end
  def im(p1, *rest, kw:); end
  define_method(:dm) { |q| }
end
puts C.method(:cm).parameters.inspect
puts C.instance_method(:im).parameters.inspect
puts C.new.method(:im).parameters.inspect
puts C.instance_method(:dm).parameters.inspect

# A C method still answers the way CRuby does.
puts [].method(:push).parameters.inspect
puts 1.method(:+).parameters.inspect
