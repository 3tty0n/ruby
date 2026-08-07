# Required by test/requires.rb; RPyYARV compiles and runs this file itself.
def lib_add(a, b)
  a + b
end

class LibCounter
  def initialize
    @n = 0
  end

  def bump(x)
    @n = @n + x
    @n
  end
end
