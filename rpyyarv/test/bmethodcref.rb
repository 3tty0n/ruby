# A define_method block resolves constants in the scope it was written in,
# not in the scope of the method it became.

module M
  OPTS = { :o => 1 }.freeze
  KIND = 'outer'

  class G
    KIND = 'inner'

    def self.add(name)
      define_method(name) { |a, opts = OPTS| [a, opts, KIND] }
    end
    add(:typed)

    define_method(:direct) { |a = OPTS| [a, KIND] }
  end
end

g = M::G.new
p g.typed(1)
p g.typed(1, {})
p g.direct

i = 0
while i < 300
  g.typed(i)
  g.direct
  i += 1
end
p g.typed(2)
p g.direct

# A plain block still reads its writer's scope.
module M
  class G
    def self.each_kind
      [1].map { KIND }
    end
  end
end
p M::G.each_kind

# module_function's define_method keeps the same scope on both copies.
module F
  WHERE = 'F'
  module_function
  define_method(:where) { WHERE }
end
p F.where
