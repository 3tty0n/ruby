# refine and using are CRuby's, and the files naming them are delegated; this
# one is not, so the refinement must stay invisible here and work there.
require_relative 'refinements_def'

p 3.respond_to?(:doubled)

begin
  p 3.doubled
rescue NoMethodError
  puts 'NoMethodError'
end

require_relative 'refinements_use'

p use_doubled(3)
p 5.respond_to?(:doubled)
p Doubler.class
