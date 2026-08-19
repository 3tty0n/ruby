# String class_eval defs must keep their cref home even when the calling
# file is delegated to CRuby (evalcref_use has `...` for that purpose).
class Module
  def my_cattr(sym)
    module_eval("def self.#{sym}=(v); @@#{sym} = v; end; def self.#{sym}; @@#{sym}; end", __FILE__, __LINE__)
  end
end
require_relative "evalcref_use"
p Used.verbose
Used.verbose = :flipped
p Used.verbose
class Direct; end
Direct.class_eval("def self.tag=(v); @@tag = v; end; def self.tag; @@tag; end")
Direct.tag = 3
p Direct.tag

# Block-form class_eval/instance_eval: consts resolve in the block's home.
module BlockHome
  BMARK = :bmark
  STORE = proc { p BMARK; $seen_self = self }
end
class EvalDst; end
EvalDst.class_eval(&BlockHome::STORE)
p $seen_self == EvalDst
o = Object.new
o.instance_eval(&BlockHome::STORE)
p $seen_self.equal?(o)

# alias inside a block-form class_eval: CBASE is the receiver, not the
# enclosing body (vm_get_cbase keeps eval-pushed crefs, CONST_BASE skips).
module Kernelish
  def greet
    :hi
  end
end
dup2 = Kernelish.dup
class AliasHost
  DUP2 = 1
  def self.wire(m)
    m.class_eval do
      alias hello greet
    end
  end
end
AliasHost.wire(dup2)
class UsesDup; include Module.new; end
UsesDup.include dup2
p UsesDup.new.hello
p UsesDup.new.greet
