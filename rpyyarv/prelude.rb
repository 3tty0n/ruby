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
  # Integer bounds only; a String or Float range needs succ, not + 1.
  def each
    return to_enum(:each) unless block_given?
    i = self.begin
    hi = self.end
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
