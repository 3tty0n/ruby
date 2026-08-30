# A block handed to Proc#call binds the proc's &param; yield still takes the
# block of the method the proc was written in.
scope = proc { |&b| b ? b.call : "none" }
p scope.call { 42 }
p scope.call
p scope.(43) rescue p $!.class
p scope.yield { 44 }
p scope[]

l = lambda { |&b| b.call }
p l.call { 45 }

def outer
  pr = proc { block_given? ? yield : "no" }
  p pr.call { 2 }
  p pr.call
end
outer { 1 }

def fwd(&blk)
  proc { |&b| b.call }.call(&blk)
end
p fwd { 5 }

class It
  def initialize(a, scope)
    @a = a
    @scope = scope
  end

  def each_with_info
    return enum_for(:each_with_info) unless block_given?
    @a.each { |o| @scope.call { yield(o, o * 2) } }
  end
end

it = It.new([1, 2, 3], proc { |&b| b.call })
it.each_with_info { |o, i| p [o, i] }
it.each_with_info.each { |o, i| p [o, i] }
