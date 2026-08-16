# Required by test/refinements.rb. A refinement is CRuby's to run: RPyYARV
# delegates the whole file rather than half-honour a lexically scoped one.
module Doubler
  refine Integer do
    def doubled
      self * 2
    end
  end
end
