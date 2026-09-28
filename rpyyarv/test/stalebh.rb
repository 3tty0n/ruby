# A block handed to a C method from code with no CRuby frame of its own must
# not stay rooted by the frame rpyyarv runs on once the call returns.

def run(wm)
  big = Object.new
  wm[big] = true
  [2, 1].sort_by { |x| big; x }
  nil
end

def scrub(n) = n == 0 ? 0 : scrub(n - 1) + 1

wm = ObjectSpace::WeakMap.new
run(wm)
scrub(30)
GC.start
GC.start
GC.start
puts wm.keys.size
