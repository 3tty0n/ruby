class Foo
  def self.bar
    "Foo.bar"
  end

  def self.add(a, b)
    a + b
  end

  def self.make(n)
    f = new
    f.set(n)
    f
  end

  def set(n)
    @n = n
    self
  end

  def n
    @n
  end
end

class Baz < Foo
  def self.bar
    "Baz.bar overrides " + super_name
  end

  def self.super_name
    "Foo"
  end
end

class Quux < Foo
end

# Called from RPyYARV.
p Foo.bar
p Foo.add(2, 3)
p Foo.make(7).n

# Inherited singleton methods.
p Quux.bar
p Quux.add(4, 5)
p Baz.bar
p Quux.make(9).n

# Dispatched by CRuby, which has to find the entry the trampoline left on the
# singleton class.
p Foo.send(:bar)
p Quux.send(:add, 6, 7)
p Foo.respond_to?(:bar)
p [Foo, Quux].map { |k| k.bar }

# A singleton method on a plain object.
obj = Foo.new
def obj.only_mine
  "singleton on an instance"
end
p obj.only_mine
p obj.respond_to?(:only_mine)
p Foo.new.respond_to?(:only_mine)

# Redefinition.
class Foo
  def self.bar
    "Foo.bar again"
  end
end
p Foo.bar
p Quux.bar
