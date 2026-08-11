# Hot paths used by ruby-bench's current performance regressions.
class RespondBase
  def visible
  end

  private

  def hidden
  end
end

class RespondChild < RespondBase
end

respond = RespondChild.new
puts respond.itself.equal?(respond)
puts respond.respond_to?(:visible)
puts respond.respond_to?(:missing)
empty = []
puts empty.reverse_each {}.equal?(empty)
puts empty.index {}.inspect

FastStruct = Struct.new(:left, :right)
st = FastStruct.new(1, 2)
puts [st.left, st.right].inspect
st.right = 'young'
GC.start
puts st.right
st.freeze
begin
  st.left = 3
rescue FrozenError
  puts 'FrozenError on Struct'
end

class ClassIvars
  @answer = 42
  def self.answer
    @answer
  end
end

module ModuleIvars
  @answer = 43
  def self.answer
    @answer
  end
end

puts ClassIvars.answer
puts ModuleIvars.answer

DefinedConstant = 1
@defined_ivar = 1
def defined_function
end
puts [defined?(DefinedConstant), defined?(MissingConstant),
      defined?(@defined_ivar), defined?(@missing_ivar),
      defined?(defined_function), defined?(missing_function)].inspect

class SingletonBody
  class << self
    def answer
      44
    end
  end
end
puts SingletonBody.answer
puts 1.succ
puts [65].pack('C', buffer: 'x')
