# ---- a constant read in a hot loop ----

LIMIT = 300
STEP  = 3
FALSY = false

def hot_sum
  i = 0
  acc = 0
  while i < LIMIT
    acc += STEP
    i += 1
  end
  acc
end

def read_falsy
  FALSY
end

puts hot_sum
puts hot_sum
i = 0
while i < 300
  read_falsy
  i += 1
end
puts read_falsy.inspect

# ---- Foo::Bar nesting ----

class Outer
  MID = 7
  class Inner
    DEEP = 11
  end
end

def nested
  Outer::MID + Outer::Inner::DEEP
end

i = 0
while i < 300
  nested
  i += 1
end
puts nested
puts ::Outer::Inner::DEEP

# ---- a constant reassigned once the cache is warm ----

MUT = 1

def read_mut
  MUT
end

i = 0
while i < 300
  read_mut
  i += 1
end
puts read_mut
MUT = 2
puts read_mut

# ---- remove_const, then a re-read ----

GONE = 'here'

def read_gone
  GONE
end

i = 0
while i < 300
  read_gone
  i += 1
end
puts read_gone
Object.send(:remove_const, :GONE)
begin
  read_gone
  puts 'no error'
rescue NameError => e
  puts "NameError #{e.name}"
end
Object.const_set(:GONE, 'again')
puts read_gone

# ---- a constant CRuby-side code defines after the cache is warm ----

def read_late
  LATE
end

i = 0
while i < 300
  begin
    read_late
  rescue NameError
  end
  i += 1
end
Object.const_set(:LATE, 42)
puts read_late

# ---- a class reopened so the same path resolves differently ----

class Base1
  KIND = 'base'
end

class Sub1 < Base1
end

def read_kind
  Sub1::KIND
end

i = 0
while i < 300
  read_kind
  i += 1
end
puts read_kind

class Sub1
  KIND = 'sub'
end

puts read_kind
puts Base1::KIND

# ---- including a module changing the resolution ----

class Host1
end

def read_mixed
  begin
    Host1::E.round(3)
  rescue NameError
    'not yet'
  end
end

i = 0
while i < 300
  read_mixed
  i += 1
end
puts read_mixed
Host1.include(Math)
puts read_mixed

# ---- one site, two receivers: the cbase is the defining class either way ----

SHARED = 'toplevel'

class ReaderBase
  SHARED = 'base'
  def read_shared
    SHARED
  end
end

class Left < ReaderBase
  SHARED = 'left'
end

class Right < ReaderBase
  SHARED = 'right'
end

l = Left.new
r = Right.new
i = 0
while i < 300
  l.read_shared
  r.read_shared
  i += 1
end
puts l.read_shared
puts r.read_shared

# ---- NameError for a missing constant ----

begin
  Object::NOPE
  puts 'no error'
rescue NameError => e
  puts "NameError #{e.name}"
end

begin
  NOPE2
  puts 'no error'
rescue NameError => e
  puts "NameError #{e.name}"
end

# ---- autoload ----

autoload :AUTOLOADED, File.expand_path('consts_auto.rb', File.dirname(__FILE__))
puts AUTOLOADED
puts AUTOLOADED

# ---- the cached VALUE has to survive a collection ----

class Holder1
  PAYLOAD = 'a heap string the cache is the only extra reference to'
end

def read_payload
  Holder1::PAYLOAD
end

i = 0
while i < 300
  read_payload
  i += 1
end
GC.start
GC.start
GC.start
puts read_payload
puts read_payload.length

# A constant reassigned inside the loop: every read has to see the new value.
class Holder1
  SWAP = 0
end

sum = 0
i = 0
while i < 100
  Holder1.send(:remove_const, :SWAP)
  Holder1.const_set(:SWAP, i)
  sum += Holder1::SWAP
  GC.start if i % 25 == 0
  i += 1
end
puts sum
# A dynamic namespace compiles to getconstant rather than opt_getconstant_path.
scope = Object
p scope::String
p eval("String")
