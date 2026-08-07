# Hot iterators as Ruby, so their loop is RPyYARV frames the JIT can trace
# rather than a CRuby rb_block_call the tracer cannot see a back edge in.

class Integer
  def times
    i = 0
    while i < self
      yield i
      i = i + 1
    end
    self
  end

  def upto(n)
    i = self
    while i <= n
      yield i
      i = i + 1
    end
    self
  end

  # Two positional arguments only; every other form (one argument, keywords,
  # no block) fails loudly in the caller rather than silently differing.
  def step(limit, step)
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
    i = 0
    while i < self.length
      yield self[i]
      i = i + 1
    end
    self
  end

  def each_index
    i = 0
    while i < self.length
      yield i
      i = i + 1
    end
    self
  end

  # Not an iterator, but the funcallv it replaces is what keeps so_matrix's
  # innermost each from tracing.
  def at(i)
    self[i]
  end
end

class Range
  # Integer bounds only; a String or Float range needs succ, not + 1.
  def each
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
