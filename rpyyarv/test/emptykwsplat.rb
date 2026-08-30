# CALLER_SETUP_ARG: an empty **splat is no argument at all, attr_* included.
class Logger
  attr_accessor :formatter
  def initialize; @formatter = :fmt; end
  def level(*args, **kwargs) = [args, kwargs]
end
def dispatch(obj, m, *args, **kwargs, &block) = obj.send(m, *args, **kwargs, &block)
l = Logger.new
p dispatch(l, :formatter)
p l.send(:formatter, **{})
p l.formatter(**{})
p dispatch(l, :formatter=, :other)
p dispatch(l, :level, 1, k: 2)
p l.level(**{})
