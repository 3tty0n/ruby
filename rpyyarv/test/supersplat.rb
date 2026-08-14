# super with a *splat: explicit, zsuper-regenerated, and landing on CRuby.
class A
  def m(a, b, c)
    [a, b, c]
  end

  def opt(a, b = 10, *rest)
    [a, b, rest]
  end
end

class B < A
  def m(*args)
    super(*args)
  end

  def opt(*args)
    super(*args)
  end
end

p B.new.m(1, 2, 3)
p B.new.opt(1)
p B.new.opt(1, 2, 3, 4)

class Z < A
  def m(a, *rest)
    super
  end
end

p Z.new.m(1, 2, 3)

class MyArr < Array
  def push(*args)
    super(*args)
  end
end

a = MyArr.new
a.push(1, 2)
p a

class MM
  def method_missing(name, *args)
    super
  end
end

begin
  MM.new.nope(1)
rescue NoMethodError
  puts 'NoMethodError'
end

# A trailing hash stays positional through a splat super.
class KW
  def take(a, h)
    [a, h]
  end
end

class KWSub < KW
  def take(*args)
    super(*args)
  end
end

p KWSub.new.take(1, { k: 2 })
