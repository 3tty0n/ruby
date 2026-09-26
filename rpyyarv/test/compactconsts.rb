# Constant caches hold a constant's VALUE without marking it: after a
# compaction moves the object, each read must still return that object.
A = [:site]
B = [:const_get]
module M; C = [:ftab]; end
D = [:hot]
def site = A
def cget = Object.const_get(:B)
def ftab(m) = m::C
def hot = (s = 0; 3000.times { s += D.size }; D)
# In a method: a dead slot of the toplevel frame would pin what it read.
def snap = [site, cget, ftab(M), hot]
$r0 = snap
# toward: :empty moves every movable object.
GC.verify_compaction_references(expand_heap: true, toward: :empty)
$junk = Array.new(100_000) { |i| "junk#{i}" }
r1 = snap
%w[site const_get ftab hot].each_with_index do |n, i|
  puts "#{n}: #{r1[i].equal?($r0[i]) ? 'ok' : 'STALE'}"
end
