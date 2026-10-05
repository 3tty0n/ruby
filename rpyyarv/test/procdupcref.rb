# define_method dups a handle Proc; class_exec reads the dup's env cref chain.
class Foo; end
class Maker
  # CRuby calls inherited, so the Proc's env is that trampoline frame's.
  def self.inherited(k)
    super
    $pr = proc { |c| c.class_exec { self } }
  end
end
class Holder; end
Class.new(Maker)
# Compaction first: the frame's cme then sits on a page it alone keeps alive.
GC.verify_compaction_references(expand_heap: true, toward: :empty)
Holder.define_method(:viaexec, $pr)
$pr = nil
h = Holder.new
r = 5.times.map do
  GC.verify_compaction_references(expand_heap: true, toward: :empty)
  h.viaexec(Foo)
end
p r
