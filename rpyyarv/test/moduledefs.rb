# Modules RPyYARV defines itself, rather than the CRuby-owned ones mixins.rb uses.

module Greet
  GREETING = "hello"

  def greet
    GREETING + " from " + label
  end

  def label
    "Greet"
  end
end

module Loud
  def shout
    greet.upcase
  end
end

class Speaker
  include Greet
  include Loud

  def label
    "Speaker"
  end
end

s = Speaker.new
puts s.greet
puts s.shout
puts s.label
puts Speaker.include?(Greet)
puts Speaker.ancestors.include?(Loud)

puts Greet::GREETING

# Reopening adds to the same module, and its includers see it at once.
module Greet
  FAREWELL = "bye"

  def part
    FAREWELL + " from " + label
  end
end
puts s.part
puts Greet::FAREWELL

# Nesting.
module Outer
  OUTER_CONST = 1

  module Inner
    INNER_CONST = 2

    def self.who
      "Outer::Inner"
    end

    def helper
      "inner helper"
    end
  end

  def self.who
    "Outer"
  end
end

puts Outer.who
puts Outer::Inner.who
puts Outer::OUTER_CONST
puts Outer::Inner::INNER_CONST

class UsesInner
  include Outer::Inner
end
puts UsesInner.new.helper

# A module method reached as Module.method, defined both ways round.
module Calc
  def self.double(n)
    n * 2
  end

  def self.quad(n)
    double(n) * 2
  end
end
puts Calc.double(21)
puts Calc.quad(3)

# module_function punts the whole file, so a module's own methods use def self.
module Util
  def self.twice(n)
    n + n
  end
end
puts Util.twice(7)

# A module included into a class defined before it gained the method.
module Late
end
class LateUser
  include Late
end
module Late
  def late_answer
    42
  end
end
puts LateUser.new.late_answer

# Same method name in two modules: the last include wins.
module First
  def pick
    "first"
  end
end
module Second
  def pick
    "second"
  end
end
class Picker
  include First
  include Second
end
puts Picker.new.pick

# super through an included module up to the class's own superclass.
class Base
  def chain
    "base"
  end
end
module Middle
  def chain
    "middle+" + super
  end
end
class Derived < Base
  include Middle
  def chain
    "derived+" + super
  end
end
puts Derived.new.chain

# Called in a loop so the JIT traces the module-owned method.
total = 0
i = 0
while i < 200
  total = total + Util.twice(i)
  i = i + 1
end
puts total
