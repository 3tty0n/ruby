# Required by blockraise.rb. The class variable is past RPyYARV's loader, so
# CRuby runs this file and its rescue/ensure sit between a block and its caller.
class BlockRaiseMarker
  @@tag = "cruby"

  def self.tag
    @@tag
  end
end

def convert
  yield
rescue => e
  raise ArgumentError, "converted #{e.class}"
end

def swallow
  yield
rescue => e
  "swallowed #{e.class}"
end

def ensured(log)
  yield
ensure
  log << "ensure"
end
