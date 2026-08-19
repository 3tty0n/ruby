# `...` keeps this file delegated to CRuby, putting Mid on the CRuby side.
def _poison(...) = nil
class Mid < Top
  def initialize
    super
    @mid = :mid
  end
end
class YieldBase
  def with_block(x)
    yield(x) + 1
  end
  def fwd(x)
    block_given? ? yield(x) * 10 : -1
  end
end
