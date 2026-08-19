# A super chain crossing the boundary twice: CRuby's super lands on a
# trampoline that must resolve from its owner, not re-derive from self.
class Top
  def initialize
    @top = :top
  end
end
require_relative "superchain_mid"
class Bot < Mid
  def initialize
    super
    @bot = :bot
  end
end
o = Bot.new
p o.instance_variable_get(:@top)
p o.instance_variable_get(:@mid)
p o.instance_variable_get(:@bot)

# define_method with an UnboundMethod copies the def; identity must hold.
codegen = Module.new
codegen.module_eval("def __temp__w(v); @x = v; end; def __temp__r; @x; end")
class Holder2; end
Holder2.define_method(:x=, codegen.instance_method(:__temp__w))
Holder2.define_method(:x, codegen.instance_method(:__temp__r))
h = Holder2.new
h.x = 41
p h.x
p Holder2.method_defined?(:x=)
class Aliased
  def orig = :orig_answer
  alias_method :other, :orig
end
p Aliased.new.other

# super carrying a block: written, forwarded via &, and suppressed by &nil.
class YieldDeriv < YieldBase
  def with_block(x)
    super(x) { |v| v * 2 } + 100
  end
  def fwd(x, &b)
    super(x, &b)
  end
  def quiet(x)
    fwd(x, &nil)
  end
end
d = YieldDeriv.new
p d.with_block(3)
p(d.fwd(4) { |v| v + 5 })
p d.quiet(9)
class NativeYieldBase
  def twice(x)
    yield(x) * 2
  end
end
class NativeYieldDeriv < NativeYieldBase
  def twice(x)
    super(x) { |v| v + 7 } - 1
  end
end
p NativeYieldDeriv.new.twice(10)

# A super with no superclass method falls back to method_missing.
class GhostBase
  def method_missing(name, *args, &blk)
    return "mm-#{name}-#{args.inspect}-#{blk ? blk.call : :noblk}" if name == :ghost
    super
  end
  def respond_to_missing?(n, priv = false)
    n == :ghost || super
  end
end
class GhostDeriv < GhostBase
  def ghost(a, **o)
    super { :fromblk }
  end
end
p GhostDeriv.new.ghost(1, x: 2)

# super inside an aliased inherited method: original name, original owner.
class NCB
  def store(k, v)
    "ncb-#{k}-#{v}"
  end
end
class MB < NCB
  def store(k, v)
    "mb(" + super + ")"
  end
end
class MapLike < MB
  alias_method :put2, :store
  alias put3 store
end
p MapLike.new.put2(:a, 1)
p MapLike.new.put3(:b, 2)
