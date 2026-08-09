# A module between the receiver's class and a class RPyYARV defined a method on
# is invisible to the registry's chain, which holds Class#superclass.
require_relative 'mixin_defs'

class MixBase
  def who; "MixBase"; end
end

class MixInclude < MixBase
  include MixWho
end
p MixInclude.new.who

class MixPrepended
  def who; "MixPrepended"; end
  prepend MixPre
end
p MixPrepended.new.who
class MixPrependedSub < MixPrepended; end
p MixPrependedSub.new.who

# Included after the subclass already exists.
class MixAfter < MixBase; end
p MixAfter.new.who
class MixAfter
  include MixWho
end
p MixAfter.new.who

# The module gains the method only after the first lookup.
class MixGrows < MixBase
  include MixLate
end
p MixGrows.new.who
MixLate.include(MixLateBody)
p MixGrows.new.who

# extend puts the module on the singleton class.
class MixExtend
  def self.who; "MixExtend.self"; end
end
p MixExtend.who
MixExtend.extend(MixWho)
p MixExtend.who
mix_obj = MixBase.new
mix_obj.extend(MixWho)
p mix_obj.who
p MixBase.new.who

# super out of a module method, both ways round.
class MixSuperInclude < MixBase
  include MixSuper
end
p MixSuperInclude.new.who

class MixSuperPrepend
  def who; "MixSuperPrepend"; end
  prepend MixPreSuper
end
p MixSuperPrepend.new.who

# super through two RPyYARV frames still climbs one step at a time.
class MixMid < MixBase
  def who; "MixMid+" + super; end
end
class MixTop < MixMid
  def who; "MixTop+" + super; end
end
p MixTop.new.who

# Comparable, which owns_identity already depends on reading right.
class MixNum
  include Comparable
  def initialize(n); @n = n; end
  def value; @n; end
  def <=>(other); @n <=> other.value; end
end
p MixNum.new(1) < MixNum.new(2)
p MixNum.new(3) == MixNum.new(3)
p MixNum.new(3) == MixNum.new(4)

# A subclass RPyYARV defined into still wins over its superclass.
class MixOverride < MixBase
  def who; "MixOverride"; end
end
p MixOverride.new.who
