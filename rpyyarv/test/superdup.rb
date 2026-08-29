# Module#dup rehomes a singleton method, so super must not lose its place.
m = Module.new do
  def self.included(base); super; puts "hook #{base}"; end
end
class Foo; end
Foo.include(m)
d = m.dup
class Bar; end
Bar.include(d)
c = m.clone
class Baz; end
Baz.include(c)
p Bar.ancestors.include?(d)
