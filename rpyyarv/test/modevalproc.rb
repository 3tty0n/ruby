# module_eval/class_eval with a premade &proc: a def inside must land on the
# receiver, as it does for a literal block. Forwardable builds every delegator
# this way, so a wrong owner is a NoMethodError at the first delegated call.

class Target; end

Target.module_eval { def in_block = :block }
gen = proc { def in_proc = :proc }
Target.module_eval(&gen)
p Target.instance_method(:in_block).owner
p Target.instance_method(:in_proc).owner
p Object.private_method_defined?(:in_proc)
p Target.new.in_proc

Target.class_eval(&proc { def via_class_eval = :ce })
p Target.instance_method(:via_class_eval).owner

# The proc's own class is not where its def goes.
class Maker
  def make
    proc { def from_maker = :maker }
  end
end
Target.module_eval(&Maker.new.make)
p Target.instance_method(:from_maker).owner
p Maker.private_method_defined?(:from_maker)

# instance_eval with a premade proc: the def lands on the receiver's singleton.
obj = Object.new
obj.instance_eval(&proc { def only_mine = :mine })
p obj.only_mine
p Object.new.respond_to?(:only_mine)

# A lambda keeps its own arity check; module_eval yields the receiver.
Target.module_eval(&lambda { |m| p m })
begin
  Target.module_eval(&lambda { :no_args })
rescue ArgumentError
  puts 'ArgumentError'
end

require 'forwardable'

class Metrics
  def font_name = 'Times'
end

class Font
  extend Forwardable
  def_delegators :@metrics, :font_name

  def initialize
    @metrics = Metrics.new
  end
end

# The hexapdf shape: an explicit receiver from another class, which only
# reaches the delegator if it was defined on Font rather than on Object.
class Reader
  def read(font)
    font.font_name
  end
end

p Reader.new.read(Font.new)
p Font.instance_method(:font_name).owner

# SingleForwardable takes the same proc through instance_eval instead.
printer = Object.new
printer.extend SingleForwardable
printer.def_delegator :@out, :upcase
printer.instance_variable_set(:@out, 'ok')
p printer.upcase
p Object.new.respond_to?(:upcase)
