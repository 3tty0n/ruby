# `...` keeps this file delegated to CRuby, putting Mid on the CRuby side.
def _poison(...) = nil
class Mid < Top
  def initialize
    super
    @mid = :mid
  end
end
