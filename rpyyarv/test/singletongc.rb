# A singleton class a cache or trace named dies with its object, and a new
# class at its recycled address never answers with the dead one's methods.

N = 1000

def defs(wm)
  o = Object.new
  def o.x; 1; end
  s = 0
  20.times { s += o.x }
  wm[o] = true
  s
end

def extends(wm)
  o = Object.new
  o.extend(Comparable)
  o.respond_to?(:clamp)
  wm[o] = true
end

def evals(wm)
  o = Object.new
  o.instance_exec { [2, 1].sort_by { |v| @v = v } }
  wm[o] = true
end

%i[defs extends evals].each do |m|
  wm = ObjectSpace::WeakMap.new
  N.times { send(m, wm) }
  4.times { GC.start }
  # A compacting GC pins every held class, so auto_compact keeps them all.
  puts "#{m} #{GC.auto_compact || wm.keys.size < N / 10}"
end

module Neg; def v; -@i; end; end
module Pos; def v; @i; end; end

def make(i)
  o = Object.new
  o.instance_variable_set(:@i, i)
  case i % 3
  when 0 then def o.v; @i; end
  when 1 then def o.v; -@i; end
  else o.extend(i.even? ? Pos : Neg)
  end
  o
end

def want(i) = i % 3 == 0 || (i % 3 == 2 && i.even?) ? i : -i

def call(o) = o.v

bad = 0
3000.times do |i|
  o = make(i)
  30.times do
    bad += 1 unless call(o) == want(i)
    bad += 1 unless [o].map(&:v)[0] == want(i)
    bad += 1 unless o.respond_to?(:v) && o.is_a?(Neg) == (i % 3 == 2 && i.odd?)
  end
  GC.start if i % 25 == 0
end
puts bad
