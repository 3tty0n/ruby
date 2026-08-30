# An exception a block raises must reach the rescue and ensure clauses of the
# CRuby frames between the block and whoever catches it.
require_relative "blockraise_helper"

class MissingT < StandardError; end

begin
  convert { raise MissingT, "boom" }
rescue ArgumentError => e
  puts "converted: #{e.message}"
rescue MissingT
  puts "BAD: MissingT skipped the rescue"
end

puts(swallow { raise MissingT, "x" })

log = []
begin
  ensured(log) { raise MissingT, "y" }
rescue MissingT => e
  puts "ensure #{log.inspect} then #{e.class}"
end

# A rescue inside the block still wins over the CRuby frame's.
puts(convert do
  begin
    raise MissingT, "inner"
  rescue MissingT
    "block rescued"
  end
end)

# The round trip leaves the enclosing rescue's $! alone.
begin
  raise KeyError, "outer"
rescue KeyError
  begin
    convert { raise MissingT }
  rescue ArgumentError
  end
  puts "dollar-bang #{$!.class}"
end

# The exception unwinds our own frames too, not just CRuby's.
def two_deep
  convert { raise MissingT, "deep" }
rescue ArgumentError => e
  "outer saw #{e.class}"
end
puts two_deep

# break and return keep the non-exception path they had.
def finder
  [1, 2, 3].each { |x| return x * 10 if x == 2 }
  :none
end
puts finder
puts([1, 2, 3].each { |x| break x + 100 if x == 2 })

puts BlockRaiseMarker.tag
