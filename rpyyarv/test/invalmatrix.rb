# Ver/I2: every host mutation of a fact a hot trace folded must reach the
# trace before its next use.  Each case warms a loop until it is compiled,
# mutates the host state from inside the loop (so the trace is live), and
# records what the loop observes after the mutation.  Output must match
# CRuby.
WARM = 3000

# The host drives the loop (Array.new calls the block back), so no
# counter of T's own prelude is exposed to the redefinitions below.
def run(name)
  seen = Array.new(WARM) { |i| yield(i) }
  puts "#{name}: #{seen[0]} #{seen[WARM / 2 - 1]} #{seen[WARM / 2]} #{seen[-1]}"
end

# method redefinition
class A; def m; 1; end; end
a = A.new
run("redefine") { |i| A.class_eval { def m; 2; end } if i == WARM / 2 - 1; a.m }

# alias over an existing method
class B; def m; 1; end; def n; 3; end; end
b = B.new
run("alias") { |i| B.class_eval { alias_method :m, :n } if i == WARM / 2 - 1; b.m }

# removal falls back to the superclass
class C0; def m; 10; end; end
class C < C0; def m; 1; end; end
c = C.new
run("remove") { |i| C.send(:remove_method, :m) if i == WARM / 2 - 1; c.m }

# undef raises
class D; def m; 1; end; end
d = D.new
run("undef") do |i|
  D.send(:undef_method, :m) if i == WARM / 2 - 1
  begin; d.m; rescue NoMethodError; :nomethod; end
end

# include inserts a module between the class and its superclass
module IM; def m; 5; end; end
class E0; def m; 10; end; end
class E < E0; end
e = E.new
run("include") { |i| E.include(IM) if i == WARM / 2 - 1; e.m }

# prepend overrides the class's own method
module PM; def m; 7; end; end
class F; def m; 1; end; end
f = F.new
run("prepend") { |i| F.prepend(PM) if i == WARM / 2 - 1; f.m }

# a subclass-only change must not be seen through the parent
class G; def m; 1; end; end
class G2 < G; end
g = G.new
run("subclass") { |i| G2.class_eval { def m; 2; end } if i == WARM / 2 - 1; g.m }

# singleton method on one receiver
class H; def m; 1; end; end
h = H.new
run("singleton") { |i| (def h.m; 9; end) if i == WARM / 2 - 1; h.m }

# visibility change
class J; def m; 1; end; end
j = J.new
run("private") do |i|
  J.send(:private, :m) if i == WARM / 2 - 1
  begin; j.m; rescue NoMethodError; :private; end
end

# constant reassignment
K1 = 1
run("const-set") do |i|
  if i == WARM / 2 - 1
    Object.send(:remove_const, :K1)
    Object.const_set(:K1, 2)
  end
  K1
end

# constant shadowed in a nearer lexical scope
module L
  X = 1
  def self.get; X; end
end
module L2
  X = 1
end
run("const-lexical") do |i|
  if i == WARM / 2 - 1
    L.send(:remove_const, :X)
    L.const_set(:X, 3)
  end
  L.get
end

# redefinition of a core operator the fast paths use
class Integer
  alias_method :__orig_plus, :+
end
run("bop-redefine") do |i|
  if i == WARM / 2 - 1
    Integer.class_eval { def +(o); __orig_plus(o).__orig_plus(100); end }
  end
  r = i + 1
  Integer.class_eval { alias_method :+, :__orig_plus } if i == WARM - 1
  r - i
end

# define_method body replaced
class M; define_method(:m) { 1 }; end
mm = M.new
run("define_method") { |i| M.send(:define_method, :m) { 2 } if i == WARM / 2 - 1; mm.m }

# method_missing added after misses were cached
class N; def method_missing(n, *) = n == :q ? 1 : super; def respond_to_missing?(n, p = false) = n == :q || super; end
nn = N.new
run("method_missing") { |i| N.class_eval { def q; 4; end } if i == WARM / 2 - 1; nn.q }

# mutation compiled and run by the host (string eval) while the trace is live
class P; def m; 1; end; end
pp_ = P.new
run("host-eval") { |i| P.class_eval("def m; 6; end") if i == WARM / 2 - 1; pp_.m }

# mutation from inside a block the host calls back (Array#each)
class Q; def m; 1; end; end
q = Q.new
run("callback") { |i| [0].each { Q.class_eval { def m; 8; end } } if i == WARM / 2 - 1; q.m }
