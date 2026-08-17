# Stress the trampoline's method-resolution cache: CRuby drives the calls
# (Array#map(&:tag), a cfunc), rpyyarv redefines the target mid-loop by both
# `def` and a `class << self` monkeypatch, and every call must see whatever
# definition is live at that moment, never one the cache remembers.
class Tag
  def self.tag
    "v1"
  end
end

seen = []
40.times do |i|
  seen << [Tag].map(&:tag).first
  if i == 10
    class Tag
      def self.tag
        "v2"
      end
    end
  end
  if i == 20
    class << Tag
      def tag
        "v3"
      end
    end
  end
  if i == 30
    class Tag
      def self.tag
        "v4"
      end
    end
  end
end

raise 'mismatch' unless seen[0, 11] == ["v1"] * 11
raise 'mismatch' unless seen[11, 10] == ["v2"] * 10
raise 'mismatch' unless seen[21, 10] == ["v3"] * 10
raise 'mismatch' unless seen[31, 9] == ["v4"] * 9
puts seen.uniq.inspect
puts seen.first
puts seen.last
puts seen[10]
puts seen[11]
puts seen[20]
puts seen[21]
puts seen[30]
puts seen[31]
