# Each rpyyarv cache that holds a raw VALUE, filled, compacted, re-read.
# ONLY=phase runs one phase, so a crash names it; COMPACT_MODE picks how.
require 'objspace'
N = (ENV['COMPACT_N'] || 2000).to_i
# compact: GC.compact; verify: also doubles the heap; empty: moves all.
# A global, not a constant: a stale const cache would corrupt the driver.
$mode = ENV['COMPACT_MODE'] || 'compact'

# Padding first, so what follows lives in pages compaction empties.
$pad = Array.new(300_000) { |i| i.even? ? Object.new : "p#{i}" }

def addr(o) = ObjectSpace.dump(o)[/"address":"(\w+)"/, 1]

def compact!
  $pad = nil
  if $mode == 'compact'
    GC.compact
  else
    toward = $mode == 'empty' ? :empty : nil
    GC.verify_compaction_references(expand_heap: true, toward: toward)
  end
  # Refill freed slots, so a stale address reads as some other object.
  $junk = Array.new(50_000) { |i| i.even? ? [i] : "junk#{i}" }
end

# ConstEntry / SiteEntry values: constants naming movable heap objects.
STR = "const-" * 3
ARY = [1, 2, [3, 4], "five"]
HSH = { "k" => "v", k2: [9] }
OBJ = Object.new.tap { |o| o.instance_variable_set(:@x, "ivar") }
Base = Class.new { def who; "base"; end }
KLASS = Class.new(Base) { def who; "sub+" + super; end }
module Outer; INNER = "inner" * 2; end

def read_consts
  s = 0
  N.times do
    s += STR.size + ARY[3].size + HSH["k"].size
    s += OBJ.instance_variable_get(:@x).size
    s += KLASS.new.who.size + Outer::INNER.size
    s += Object.const_get(:STR).size + Outer.const_get(:INNER).size
  end
  [s, STR, ARY, HSH, OBJ.instance_variable_get(:@x), KLASS.new.who,
   Outer::INNER, Object.const_get(:HSH)]
end

# owners.rtab / by_sym: dynamic Symbols as respond_to?/send names.
class Dyn
  20.times { |i| define_method(:"dyn_m#{i}") { i } }
  def method_missing(name, *)
    name.to_s.start_with?("ghost") ? name.size : super
  end
  def respond_to_missing?(name, _ = false) = name.to_s.start_with?("ghost")
end

def dyn_syms
  d = Dyn.new
  s = 0
  N.times do |j|
    i = j % 20
    sym = "dyn_m#{i}".to_sym
    s += d.send(sym) if d.respond_to?(sym)
    g = "ghost#{i}".to_sym
    s += d.send(g) if d.respond_to?(g)
    s += 1000 if d.respond_to?("nope#{i}".to_sym)
  end
  s
end

# enc_cache: Encoding objects cached by name.
def encs
  s = 0
  N.times do
    s += 1 if Encoding.find("UTF-8").equal?(Encoding::UTF_8)
    s += 1 if Encoding.find("ASCII-8BIT") == Encoding::BINARY
  end
  euc = "x".dup.force_encoding(Encoding.find("EUC-JP"))
  [s, Encoding.find("UTF-8").name, euc.encoding.name]
end

# Classes made at run time: Struct, Class.new, singleton classes.
Pt = Struct.new(:x, :y) { def sum = x + y }
def made_classes
  s = 0
  N.times do |i|
    c = Class.new(Base) { define_method(:k) { i } }
    s += c.new.k + Pt.new(i, 1).sum
    o = Object.new
    def o.sing = 7
    s += o.sing
  end
  s
end

# Trampolines: C code calling back into rpyyarv methods, and method_missing.
class Tramp
  def foo = 3
  def <=>(o) = 0
  def method_missing(n, *) = n == :bar ? 5 : super
  def respond_to_missing?(n, _ = false) = n == :bar
end

def trampolines
  t = Array.new(8) { Tramp.new }
  s = 0
  N.times do
    s += t.map(&:foo).sum + t.map(&:bar).sum
    s += t.sort.size + t.public_send(:size)
    s += t[0].__send__(:bar)
  end
  s
end

# registry.supers beyond MAX_ANCESTORS (64): a 70-deep chain.
Root = Class.new { def root_m = 11 }
$chain = Root
70.times { |i| $chain = Class.new($chain) { define_method(:"l#{i}") { i } } }
Leaf = $chain
def deep
  l = Leaf.new
  s = 0
  N.times { s += l.root_m + l.l0 + l.l69 }
  [s, Leaf.ancestors.size]
end

# Globals, not constants: the driver must not read through a const cache.
$phases = %i[read_consts dyn_syms encs made_classes trampolines deep]
$phases &= [ENV['ONLY'].to_sym] if ENV['ONLY']
$names = %w[STR ARY HSH OBJ Base KLASS INNER Dyn Pt Tramp Root Leaf UTF_8]
$tracked = [STR, ARY, HSH, OBJ, Base, KLASS, Outer::INNER, Dyn, Pt, Tramp,
            Root, Leaf, Encoding::UTF_8]

def run_phase(m)
  send(m)
rescue Exception => e
  "#{e.class}: #{e.message[0, 100]}"
end

$before = $phases.map { |m| run_phase(m) }
3.times do |round|
  was = $tracked.map { |o| addr(o) }
  compact!
  moved = $tracked.each_index.select { |i| addr($tracked[i]) != was[i] }
  $stderr.puts "round #{round}: #{moved.size}/#{$tracked.size} tracked moved" \
               " (#{moved.map { $names[_1] }.join(' ')})"
  $phases.each_with_index do |m, i|
    got = run_phase(m)
    res = got == $before[i] ? 'ok' : "MISMATCH #{got.inspect[0, 200]}"
    puts "round #{round} #{m}: #{res}"
  end
end
p $before
