# `...` keeps this file delegated to CRuby, so build_pair runs CRuby-side.
def _poison(...) = nil
module DefineHelper
  def build_pair(name)
    Maker.plant(self, name)
  end
end
