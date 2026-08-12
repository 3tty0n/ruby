module Outer
end
class Outer::Inner
  def hi = "inner"
end
p Outer::Inner.new.hi
p Outer::Inner.name

module Outer::Mod
  def self.hi = "mod"
end
p Outer::Mod.hi

class Base
  def who = "base"
end
class Outer::Sub < Base
  def who = "sub/" + super
end
p Outer::Sub.new.who

class Outer::Inner
  def hi2 = "reopened"
end
p Outer::Inner.new.hi2

O2 = Outer
class O2::Third
end
p Outer::Third.name

module Deep; module Er; end; end
class Deep::Er::Most
  CONST = 5
  def c = CONST
end
p Deep::Er::Most.new.c
p Deep::Er::Most.name

begin
  klass = 7
  eval("class klass::Nope; end")
rescue TypeError, SyntaxError, NameError
  p :refused
end
