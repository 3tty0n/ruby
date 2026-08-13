# alias of an attr, a nested class named like a top-level one, and super with
# keywords into a method CRuby owns.

class Base
  attr_reader :children
  attr_accessor :slot

  def initialize(c)
    @children = c
  end
  alias to_a children
  alias put slot=
end

b = Base.new([1, 2])
puts b.to_a.inspect
puts Base.instance_methods(false).sort.inspect
puts b.respond_to?(:to_a)
puts Base.instance_method(:to_a).arity
b.put 9
puts b.slot

class Sub < Base
  alias node_parts to_a
end
puts Sub.new([3]).node_parts.inspect

# A nested class must not reopen the same-named top-level one.
class Compiler
  class Binding; end
  class Comparable2; end
end
puts Compiler::Binding.equal?(::Binding)
puts Compiler::Binding.name
puts Compiler.const_defined?(:Binding, false)
puts Compiler::Binding.new.class
puts Compiler.constants.sort.inspect

module Outer
  class Struct2; end
end
puts Outer::Struct2.name

# super with keywords into a method CRuby owns.
class Cloner
  def clone(x = nil)
    super(freeze: false)
  end
end
puts Cloner.new.clone(1).class

class KwSplat
  def clone(x = nil)
    super(**{ freeze: false })
  end
end
puts KwSplat.new.clone(1).class

# ...and super with keywords into an RPyYARV-owned method still works.
class KBase
  def go(a, k: 0) = "#{a}/#{k}"
end
class KSub < KBase
  def go(a, k: 0) = super(a, k: k + 1)
end
puts KSub.new.go(5, k: 1)

# __method__ and __callee__ read the running frame, which CRuby cannot see.
def named; __method__; end
puts named.inspect
def aliased_orig; __callee__; end
alias aliased_new aliased_orig
puts aliased_orig.inspect
class Named
  def m; [__method__, [1].map { __method__ }]; end
end
puts Named.new.m.inspect
puts __method__.inspect
def enum_self; to_enum(__method__); end
puts enum_self.class
