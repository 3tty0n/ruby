# Block arguments: &blk parameters, block pass-through, escaping Procs.

def call_it(&b)
  b.call(1)
end
puts call_it { |x| x * 2 }

def take(&b)
  b
end
def hand_on(&b)
  take(&b).call(7)
end
puts hand_on { |x| x + 1 }

def sum_with(a, &b)
  a.each(&b)
end
total = 0
sum_with([1, 2, 3]) { |x| total = total + x }
puts total

def given?(&b)
  if b
    'yes'
  else
    'no'
  end
end
puts given?
puts given? { 1 }

class Holder
  def keep(&b)
    @blk = b
    nil
  end

  def later(n)
    @blk.call(n)
  end
end
h = Holder.new
h.keep { |x| x * 10 }
puts h.later(4)
puts h.later(5)

def twice(&b)
  b.call(1) + b.call(2)
end
puts twice { |x| x * 100 }

def none(&b)
  b == nil
end
puts none

def to_strings(a)
  a.map(&:to_s)
end
puts to_strings([1, 2, 3]).join(',')

def apply_sym(a, &b)
  a.map(&b)
end
puts apply_sym([4, 5]) { |x| x - 1 }.join(',')

# A block passed on twice, through a method that only forwards it.
def inner(&b)
  b.call(3)
end
def middle(&b)
  inner(&b)
end
def outer(&b)
  middle(&b)
end
puts outer { |x| x * x }

# yield still reaches the block a &b parameter also names.
def both(&b)
  yield(1) + b.call(2)
end
puts both { |x| x * 3 }

# A Proc that outlives every frame that made it.
def maker(n)
  make_adder(n)
end
def make_adder(n)
  keep_proc { |x| x + n }
end
def keep_proc(&b)
  b
end
add3 = maker(3)
puts add3.call(4)
puts add3.call(10)

# A materialised Proc handed back to a CRuby method as its block.
def each_with(a, &b)
  p = b
  a.each(&p)
end
seen = []
each_with([7, 8]) { |x| seen.push(x) }
puts seen.join(',')

procs = []
i = 0
while i < 5
  procs.push(keep_proc { |x| x * i })
  i = i + 1
end
out = []
procs.each { |p| out.push(p.call(2)) }
puts out.join(',')

# break unwinds to the send the block was written at, not to one that only
# forwarded it.
def b_inner(&b)
  b.call(3)
  99
end
def b_middle(&b)
  b_inner(&b)
  88
end
def b_outer(&b)
  b_middle(&b)
  77
end
puts(b_outer { |x| break x * 2 })
puts(b_outer { |x| x * 2 })
