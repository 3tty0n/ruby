# ---- a class reads its own ivars through a self-method ----

class Holder
  @num = 7
  @str = 'held'
  @nilv = nil

  def self.num
    @num
  end

  def self.str
    @str
  end

  def self.nilv
    @nilv
  end

  def self.missing
    @nope
  end

  def self.sum(n)
    s = 0
    i = 0
    while i < n
      s += @num
      i += 1
    end
    s
  end
end

puts Holder.num
puts Holder.str
puts Holder.nilv.inspect
puts Holder.missing.inspect
puts Holder.instance_variable_get(:@num)
puts Holder.instance_variable_defined?(:@nope)

# ---- a module does the same ----

module Mod
  @num = 11
  @str = 'modded'

  def self.num
    @num
  end

  def self.str
    @str
  end

  def self.missing
    @nope
  end

  def self.sum(n)
    s = 0
    i = 0
    while i < n
      s += @num
      i += 1
    end
    s
  end
end

puts Mod.num
puts Mod.str
puts Mod.missing.inspect

# ---- warm the reads, then grow the shape and read again ----

puts Holder.sum(2000)
puts Mod.sum(2000)

class Holder
  @g0 = 100
  @g1 = 200
  @g2 = 300
  @g3 = 400
  @g4 = 500

  def self.g4
    @g4
  end
end

puts Holder.num
puts Holder.g4
puts Holder.sum(2000)

# ---- a store from Ruby is visible to the next read ----

Holder.instance_variable_set(:@num, 42)
puts Holder.num
puts Holder.sum(1000)
Holder.instance_variable_set(:@nope, 'now here')
puts Holder.missing.inspect
Holder.instance_variable_set(:@str, 'replaced')
puts Holder.str

# ---- class ivars are not inherited ----

class Child < Holder
  def self.own
    @num
  end
end

puts Child.own.inspect
puts Child.num
Child.instance_variable_set(:@num, -1)
puts Child.own
puts Holder.num
puts Holder.instance_variables.inspect
puts Child.instance_variables.inspect

# ---- a hot loop of 1M reads ----

class Hot
  @v = 3

  def self.run
    s = 0
    i = 0
    while i < 1000000
      s += @v
      i += 1
    end
    s
  end
end

puts Hot.run

# ---- a singleton class and a frozen module still read right ----

obj = Object.new
class << obj
  @meta = 'singleton'

  def self.meta
    @meta
  end
end
puts obj.singleton_class.meta

module Frozen
  @v = 'cold'

  def self.v
    @v
  end
end
Frozen.freeze
puts Frozen.v
puts Frozen.frozen?
