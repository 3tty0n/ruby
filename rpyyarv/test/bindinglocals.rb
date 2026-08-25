# ---- Binding#local_variable_get over a method's own locals ----

class Proxy
  def initialize(name, alias: nil, type_lookup: nil)
    @name = name
    @alias = binding.local_variable_get(:alias)
    @type_lookup = type_lookup
  end

  attr_reader :name, :alias, :type_lookup
end

p Proxy.new(:a, alias: :b, type_lookup: :c).alias
p Proxy.new(:a).alias

def locals_here
  x = 1
  y = 'two'
  b = binding
  [b.local_variable_get(:x), b.local_variable_get(:y),
   b.local_variable_defined?(:x), b.local_variable_defined?(:zz),
   b.local_variables.sort]
end

p locals_here

def block_scope
  outer = 7
  [1].map { |i| binding.local_variable_get(:outer) + i }
end

p block_scope

def missing_name
  binding.local_variable_get(:nope)
rescue NameError => e
  e.class
end

p missing_name

i = 0
while i < 300
  locals_here
  i += 1
end
p locals_here.first
