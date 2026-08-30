# Dispatch must not run a user Module#instance_method: delegate.rb defines one.
require "delegate"
class Target
  def foo = :foo
end
D = DelegateClass(Target)
d = D.new(Target.new)
p d.foo
begin
  d.nope
rescue NoMethodError => e
  puts e.message
end
p D.instance_method(:foo).name
