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

  def select
    return to_enum(:select) unless block_given?
    out = []
    i = 0
    while i < self.length
      v = self[i]
      out << v if yield v
      i = i + 1
    end
    out
  end
  alias_method :filter, :select

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

class Integer
  # `& 1` folds to one masked compare in a trace; the C even? was a full send.
  def even? = self & 1 == 0
  def odd? = self & 1 == 1
end

module Enumerable
  # Covers every enumerable whose #each is native (Hash, and rubykon's Board);
  # Array#inject also lands here, since CRuby defines inject on Enumerable only.
  def inject(*args)
    init_given = false
    init = nil
    sym = nil
    if args.length == 1
      if block_given?
        init = args[0]
        init_given = true
      else
        sym = args[0]
      end
    elsif args.length == 2
      init = args[0]
      init_given = true
      sym = args[1]
    end
    acc = init
    first = !init_given
    each do |*e|
      v = e.length == 1 ? e[0] : e
      if first
        acc = v
        first = false
      elsif sym
        acc = acc.__send__(sym, v)
      else
        acc = yield(acc, v)
      end
    end
    acc
  end
  alias_method :reduce, :inject

  def map
    return to_enum(:map) unless block_given?
    out = []
    each do |*e|
      out << (e.length == 1 ? yield(e[0]) : yield(e))
    end
    out
  end
  alias_method :collect, :map

  def find
    return to_enum(:find) unless block_given?
    each do |*e|
      v = e.length == 1 ? e[0] : e
      return v if yield(v)
    end
    nil
  end
  alias_method :detect, :find
end

class Array
  def empty? = length == 0

  def first(*args)
    return self[0] if args.length == 0
    self[0, args[0]]
  end

  def last(*args)
    return self[length - 1] if args.length == 0
    n = args[0]
    n = length if n > length
    self[length - n, n]
  end

  def include?(obj)
    i = 0
    while i < self.length
      return true if self[i] == obj
      i = i + 1
    end
    false
  end

  def count(*args)
    if args.length == 0
      return length unless block_given?
      n = 0
      i = 0
      while i < self.length
        n += 1 if yield self[i]
        i = i + 1
      end
      n
    else
      obj = args[0]
      n = 0
      i = 0
      while i < self.length
        n += 1 if self[i] == obj
        i = i + 1
      end
      n
    end
  end

  def any?(*args)
    if args.length == 1
      pat = args[0]
      i = 0
      while i < self.length
        return true if pat === self[i]
        i = i + 1
      end
      return false
    end
    i = 0
    if block_given?
      while i < self.length
        return true if yield self[i]
        i = i + 1
      end
    else
      while i < self.length
        return true if self[i]
        i = i + 1
      end
    end
    false
  end

  def all?(*args)
    if args.length == 1
      pat = args[0]
      i = 0
      while i < self.length
        return false unless pat === self[i]
        i = i + 1
      end
      return true
    end
    i = 0
    if block_given?
      while i < self.length
        return false unless yield self[i]
        i = i + 1
      end
    else
      while i < self.length
        return false unless self[i]
        i = i + 1
      end
    end
    true
  end
end

class Hash
  # These walk a flat [k0, v0, ...] snapshot, one C call for the whole hash,
  # so mutation during iteration is not the error CRuby raises.
  def each
    return to_enum(:each) unless block_given?
    ps = __rpyyarv_hash_pairs__(self)
    i = 0
    while i < ps.length
      yield [ps[i], ps[i + 1]]
      i = i + 2
    end
    self
  end
  alias_method :each_pair, :each

  def each_key
    return to_enum(:each_key) unless block_given?
    ks = keys
    i = 0
    while i < ks.length
      yield ks[i]
      i = i + 1
    end
    self
  end

  def select
    return to_enum(:select) unless block_given?
    out = {}
    ps = __rpyyarv_hash_pairs__(self)
    i = 0
    while i < ps.length
      k = ps[i]
      v = ps[i + 1]
      out[k] = v if yield k, v
      i = i + 2
    end
    out
  end
  alias_method :filter, :select

  def merge!(*others)
    i = 0
    while i < others.length
      ps = __rpyyarv_hash_pairs__(others[i])
      j = 0
      while j < ps.length
        k = ps[j]
        v = ps[j + 1]
        if block_given? && key?(k)
          self[k] = yield(k, self[k], v)
        else
          self[k] = v
        end
        j = j + 2
      end
      i = i + 1
    end
    self
  end
  alias_method :update, :merge!

  # fetch never consults the default; key? then [] only touches stored pairs.
  def fetch(*args)
    n = args.length
    if n == 0 || n > 2
      raise ArgumentError, "wrong number of arguments (given #{n}, expected 1..2)"
    end
    k = args[0]
    return self[k] if key?(k)
    return yield(k) if block_given?
    return args[1] if n == 2
    raise KeyError.new("key not found: #{k.inspect}", receiver: self, key: k)
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
  def tap
    yield self
    self
  end

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

