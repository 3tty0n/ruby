# Required by trampoline.rb, and itself requiring a file only CRuby can load:
# the case the _DelegateChain rule used to send to CRuby as well.
require_relative "trampoline_delegate"

# DelegatedBase#describe is CRuby's and dispatches #label back into RPyYARV.
class DelegatedSub < DelegatedBase
  def label
    "sub"
  end
end
