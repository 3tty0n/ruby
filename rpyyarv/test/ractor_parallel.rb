Warning[:experimental] = false

def ractor_sum(limit)
  sum = 0
  i = 0
  while i < limit
    sum += i
    i += 1
  end
  sum
end

class NativeMethodHookProbe
  @added = []

  def self.method_added(name)
    @added << name
  end

  def self.added
    @added
  end

  def sum(limit)
    ractor_sum(limit)
  end
end

module NativeLexicalScope
  OFFSET = 7

  class Base
    def sum(limit)
      ractor_sum(limit)
    end
  end

  class Child < Base
    def sum(limit)
      super + OFFSET
    end
  end
end

unless NativeMethodHookProbe.added == [:sum]
  raise 'native shadow method fired method_added'
end

expected = 19_999_900_000
3.times do
  ractors = 4.times.map do
    Ractor.new { NativeLexicalScope::Child.new.sum(200_000) - 7 }
  end
  raise 'wrong parallel result' unless ractors.map(&:value) == [expected] * 4
end

puts 'ok'
