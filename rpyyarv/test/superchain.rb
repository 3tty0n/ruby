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
