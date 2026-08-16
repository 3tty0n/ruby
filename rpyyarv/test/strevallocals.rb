# String class_eval/module_eval runs in the caller's local scope, as
# eval_string_with_cref does (vm_eval.c:2269). hexapdf's Utils::BitField
# interpolates one such local into the source it generates.

class C; end

def read_one
  x = 1
  C.module_eval('p x')
end
read_one

# An assignment inside the string reaches the caller's local.
def write_back
  x = 1
  C.module_eval('x = 99')
  p x
end
write_back

# A local the string alone introduces does not leak out.
def no_leak
  C.module_eval('fresh = 5')
  p defined?(fresh)
end
no_leak

def shadow
  x = 1
  C.module_eval('x = 2; p x')
  p x
end
shadow

# A block written in the string captures the caller's locals too.
def in_block
  x = 7
  C.module_eval('p [1].map { x }')
end
in_block

# The caller is itself a block: its own parameter and the method's local.
def from_block
  outer = 3
  [1].each do |i|
    C.module_eval('p [outer, i]')
  end
end
from_block

# The file and line arguments reach the compiler. Not source_location, which
# is nil for every method RPyYARV defines, nor Exception#backtrace, which sees
# no RPyYARV frame at all.
def with_file
  C.module_eval('def where; [__FILE__, __LINE__]; end', 'made_up.rb', 42)
end
with_file
p C.new.where

# The hexapdf shape: a constant and method bodies generated from a local.
module BitField
  def bit_field(name)
    mapping = { a: 0, b: 1 }
    module_eval(<<-EOF, __FILE__, __LINE__ + 1)
      #{name.upcase}_MAP = mapping.freeze
      def #{name}_get(key)
        self.class::#{name.upcase}_MAP[key]
      end
    EOF
  end
end

class Doc
  extend BitField
  bit_field(:raw)
end

p Doc.new.raw_get(:b)
p Doc::RAW_MAP
p Doc.instance_method(:raw_get).owner
p Doc.new.raw_get(:a)
