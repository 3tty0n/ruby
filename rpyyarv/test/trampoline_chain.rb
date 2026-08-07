# Required by trampoline.rb, and itself requiring a file only CRuby can load:
# the case the _PuntChain rule used to send to CRuby as well.
require_relative "trampoline_punt"

# PuntBase#describe is CRuby's and dispatches #label back into RPyYARV.
class PuntSub < PuntBase
  def label
    "sub"
  end
end
