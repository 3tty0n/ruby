# `...` keeps this file delegated to CRuby, so hidden is a CRuby method.
def _poison(...) = nil
class KH
  def make_proc
    proc { :from_cruby }
  end
  private
  def hidden(&b)
    b.call
  end
end
