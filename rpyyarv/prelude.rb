# Hot iterators as Ruby, so their back edge is one the JIT can trace rather than a CRuby rb_block_call it cannot see into.
# Each keeps CRuby's no-block arm: without it `[1,2].each` yields instead of answering an Enumerator.

class Integer
  def times
    return to_enum(:times) unless block_given?
    i = 0
    while i < self
      yield i
      i = i + 1
    end
    self
  end

  def upto(n)
    return to_enum(:upto, n) unless block_given?
    i = self
    while i <= n
      yield i
      i = i + 1
    end
    self
  end

  # Two positional arguments only; every other form fails loudly in the caller.
  def step(limit, step)
    return to_enum(:step, limit, step) unless block_given?
    i = self
    if step > 0
      while i <= limit
        yield i
        i = i + step
      end
    else
      while i >= limit
        yield i
        i = i + step
      end
    end
    self
  end

  def downto(n)
    return to_enum(:downto, n) unless block_given?
    i = self
    while i >= n
      yield i
      i = i - 1
    end
    self
  end
end

class Array
  def each
    return to_enum(:each) unless block_given?
    i = 0
    while i < self.length
      yield self[i]
      i = i + 1
    end
    self
  end

  def each_index
    return to_enum(:each_index) unless block_given?
    i = 0
    while i < self.length
      yield i
      i = i + 1
    end
    self
  end

  # Not an iterator: the funcallv it replaces kept so_matrix's innermost each
  # from tracing.
  def at(i)
    self[i]
  end
end

class Range
  def each
    return to_enum(:each) unless block_given?
    i = self.begin
    hi = self.end
    # Only an Integer range steps by +1; a String one needs succ, so CRuby's
    # own Range#to_a walks it and this only drives the block.
    unless i.is_a?(Integer) && hi.is_a?(Integer)
      a = self.to_a
      j = 0
      while j < a.length
        yield a[j]
        j = j + 1
      end
      return self
    end
    if self.exclude_end?
      while i < hi
        yield i
        i = i + 1
      end
    else
      while i <= hi
        yield i
        i = i + 1
      end
    end
    self
  end
end

module Kernel
  # splay!'s tree descent is a `loop do`, whose every iteration would otherwise
  # cross into rb_block_call and back through the ifunc bridge.
  def loop
    return to_enum(:loop) unless block_given?
    begin
      while true
        yield
      end
    rescue StopIteration => e
      e.result
    end
  end
end
