# remove_method / undef_method / private / public: intercepted the way
# module_function and private_class_method already are, since none of them
# reach CRuby's own send with RPyYARV's registry in view.

class RM
  def m
    1
  end
end
r = RM.new
puts r.m
RM.send(:remove_method, :m)
begin
  r.m
rescue NoMethodError => e
  puts "remove: #{e.message}"
end

# remove_method exposes the parent's method; undef_method must not.
class RMP
  def m
    :parent
  end
end
class RMC < RMP
  def m
    :child
  end
end
RMC.send(:remove_method, :m)
puts "remove_parent_exposed: #{RMC.new.m}"

class UMP
  def m
    :parent
  end
end
class UMC < UMP
  def m
    :child
  end
end
UMC.send(:undef_method, :m)
begin
  UMC.new.m
rescue NoMethodError => e
  puts "undef_parent_blocked: #{e.message}"
end

begin
  RM.send(:remove_method, :nonexistent)
rescue NameError => e
  puts "remove_nonexistent: #{e.class}"
end
begin
  RM.send(:undef_method, :nonexistent)
rescue NameError => e
  puts "undef_nonexistent: #{e.class}"
end

# Bare `private` flips the body's default; `public` flips it back.
class Vis
  private

  def bar
    1
  end

  public

  def baz
    2
  end
end
begin
  Vis.new.bar
rescue NoMethodError => e
  puts "private_explicit_receiver: #{e.message}"
end
puts "private_send: #{Vis.new.send(:bar)}"
puts "public_call: #{Vis.new.baz}"

class ViaSelf
  private

  def bar
    1
  end

  public

  def call_bar
    bar
  end
end
puts "private_implicit_self: #{ViaSelf.new.call_bar}"

# `private :name` after the fact, and `private def x; end`.
class NamedPrivate
  def m
    1
  end
  private :m
end
begin
  NamedPrivate.new.m
rescue NoMethodError => e
  puts "private_name_form: #{e.message}"
end

class PrivateDef
  private def m
    1
  end
end
begin
  PrivateDef.new.m
rescue NoMethodError => e
  puts "private_def_form: #{e.message}"
end

# `private :name` on a name only the ancestor owns: CRuby gives the
# receiver its own private override, and the parent's copy stays public.
class NamedPrivateParent
  def m
    :parent
  end
end
class NamedPrivateChild < NamedPrivateParent
  private :m
end
begin
  NamedPrivateChild.new.m
rescue NoMethodError => e
  puts "private_name_inherited: #{e.message}"
end
puts "private_name_inherited_parent: #{NamedPrivateParent.new.m}"

# define_method and attr_accessor both pick up the body's default visibility.
class PrivateBmethod
  private

  define_method(:m) { 1 }
end
begin
  PrivateBmethod.new.m
rescue NoMethodError => e
  puts "private_define_method: #{e.message}"
end

class PrivateAttr
  private

  attr_accessor :x
end
begin
  PrivateAttr.new.x = 1
rescue NoMethodError => e
  puts "private_attr_accessor: #{e.message}"
end
