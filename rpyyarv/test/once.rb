def build(x)
  # /o caches the regexp after the first evaluation, interpolation and all.
  /pre#{x}post/o
end
p build("A").source
p build("B").source
p build("C").source

class L
  IGNORE = %r{
    (?:
      [\ \t\n]+
    )+
  }x
  def initialize(s) = @s = s
  def skip = @s =~ IGNORE ? "ws" : "no"
end
p L.new("   x").skip
p L.new("x").skip

R = 3
def once_const
  /v#{R}/o
end
p once_const.match?("v3")
p once_const.match?("v3")

def twice
  a = 0
  2.times { a += 1 }
  /count#{a}/o
end
p twice.source
p twice.source
