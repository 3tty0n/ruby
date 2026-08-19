class KwSink
  def sink(a, b: 0)
    [a, b]
  end
end
class KwFwd
  ruby2_keywords def fwd(*args, &blk)
    KwSink.new.sink(*args, &blk)
  end
end
p KwFwd.new.fwd(1, b: 2)
p KwFwd.new.fwd(3)
class MMFwd
  def initialize(target)
    @t = target
  end
  ruby2_keywords def method_missing(name, *args, &blk)
    @t.public_send(name, *args, &blk)
  end
  def respond_to_missing?(n, p = false)
    @t.respond_to?(n) || super
  end
end
p MMFwd.new(KwSink.new).sink(5, b: 6)
h = { b: 9 }
p KwFwd.new.fwd(8, **h)
p h.frozen? == false && h == { b: 9 }
