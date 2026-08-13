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

  def map
    return to_enum(:map) unless block_given?
    out = []
    i = 0
    while i < self.length
      out << yield(self[i])
      i = i + 1
    end
    out
  end

  # The block arm only; liquid's scope walk calls it per variable lookup.
  def find_index(*args)
    if args.length == 0
      return to_enum(:find_index) unless block_given?
      i = 0
      while i < self.length
        return i if yield self[i]
        i = i + 1
      end
      nil
    elsif args.length == 1
      obj = args[0]
      i = 0
      while i < self.length
        return i if self[i] == obj
        i = i + 1
      end
      nil
    else
      raise ArgumentError, "wrong number of arguments (given #{args.length}, expected 0..1)"
    end
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

# CRuby's own caller/caller_locations see no Ruby frames, since RPyYARV runs
# them without pushing a CRuby control frame: they answer [] or nil, and a
# `caller_locations(1, 1).first` (ActiveSupport does this per delegated method)
# raises. These read RPyYARV's own frame chain instead.
module RPyYARV
  # A Struct, not a class of its own: prelude methods get no CRuby trampoline
  # (enable_trampolines runs after this file), so an `initialize` defined here
  # would be invisible to the Class#new that CRuby runs. Nothing here is a real
  # Thread::Backtrace::Location; only #path and #lineno are widely read.
  Location = Struct.new(:path, :lineno, :label)

  class Location
    def absolute_path = path
    def base_label = label
    def to_s = "#{path}:#{lineno}:in '#{label}'"
  end

  # Every frame, innermost first. The primitive already drops this file's own
  # frames, so index 0 is the caller of Kernel#caller_locations below.
  def self.locations
    raw = __rpyyarv_backtrace__
    out = []
    i = 0
    while i < raw.length
      out << Location.new(raw[i], raw[i + 1], raw[i + 2])
      i = i + 3
    end
    out
  end
end

module Kernel
  def caller_locations(start = 1, length = nil)
    if start.is_a?(Range)
      length = start.size
      start = start.begin
    end
    all = RPyYARV.locations
    # nil only once start walks off the stack, as rb_f_caller_locations answers it.
    return nil if start > all.length
    out = all[start..]
    length ? out[0, length] : out
  end

  def caller(start = 1, length = nil)
    locs = caller_locations(start, length)
    return nil unless locs
    out = []
    i = 0
    while i < locs.length
      l = locs[i]
      out << "#{l.path}:#{l.lineno}:in '#{l.label}'"
      i = i + 1
    end
    out
  end
end

