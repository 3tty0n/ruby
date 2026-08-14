module M
  module_function

  def one = 1
  def add(a, b) = a + b
  def uses_other = one + 1
end

p M.one
p M.add(2, 3)
p M.uses_other
p M.singleton_methods.sort
p M.private_instance_methods(false).sort
begin
  Object.new.extend(M).one
rescue NoMethodError => e
  puts "private: #{ e.class }"
end

module N
  def named = :named
  def plain = :plain
  module_function :named
end

p N.named
p N.singleton_methods.sort
p N.private_instance_methods(false).sort
begin
  N.plain
rescue NoMethodError
  puts "plain is not a module function"
end

module O
  module_function
  def a = 1
end

module O
  def b = 2
end

p O.singleton_methods.sort

class C
  include N
  def call_named = named
end
p C.new.call_named

# module_function(name) from inside a method body, as fileutils.rb's
# private_module_function does.
module P
  def self.privatize(name)
    module_function(name)
    private_class_method(name)
  end

  def util(x)
    x * 2
  end
  privatize :util
end
p P.send(:util, 21)
begin
  P.util(1)
rescue NoMethodError
  puts 'util is private on the singleton'
end
