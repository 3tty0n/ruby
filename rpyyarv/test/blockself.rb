# A bmethod defined while CRuby's current receiver equals the future caller:
# the rebind test must still see the rebind (self below must be Pair).
module Maker
  def self.plant(owner, name)
    state = [0]
    owner.singleton_class.define_method(name) { [state[0], self] }
    owner.singleton_class.define_method(:"#{name}=") { |v| state[0] = v }
  end
end
require_relative "blockself_use"
class Pair; extend DefineHelper; end
Pair.build_pair(:val)
Pair.val = 7
got = Pair.val
p got[0]
p got[1]
