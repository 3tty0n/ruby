# A block in an RPyYARV method: Integer#times is the prelude's, so the whole
# unwind stays inside RPyYARV.
def first_over(limit)
  10.times do |i|
    return i if i > limit
  end
  -1
end
p first_over(3)
p first_over(100)

# The AWFY harness shape: `return false unless ...` inside a counted loop.
def all_true(n)
  n.times do |i|
    return false unless i < 5
  end
  true
end
p all_true(3)
p all_true(9)

# Nested blocks: the return names the method, not the inner block.
def find_pair(rows)
  rows.each do |row|
    row.each do |v|
      return v if v > 10
    end
  end
  nil
end
p find_pair([[1, 2], [3, 40], [5]])

# A block passed to a CRuby builtin: Hash#each and Array#find_index are C,
# so the unwind has to cross rb_block_call.
def key_for(h, want)
  h.each do |k, v|
    return k if v == want
  end
  :none
end
p key_for({ :a => 1, :b => 2 }, 2)

def first_long(words)
  words.each_with_index do |w, i|
    return [i, w] if w.length > 3
  end
  nil
end
p first_long(["ab", "cde", "fghi", "j"])

# ...and the value is not nil.
def truthy
  [1].each { return "a string" }
  "not reached"
end
p truthy

# ensure blocks between the block and the target must run, innermost first.
def with_ensure
  begin
    begin
      [1, 2].each do |i|
        begin
          return "returned #{i}"
        ensure
          puts "inner ensure"
        end
      end
    ensure
      puts "middle ensure"
    end
  ensure
    puts "outer ensure"
  end
end
p with_ensure

# An ensure that runs while the unwind crosses a CRuby frame.
def ensure_across_c
  {:k => 1}.each do |k, v|
    begin
      return k
    ensure
      puts "ensure inside a C-called block"
    end
  end
end
p ensure_across_c

# A return whose target already returned: the orphaned Proc LocalJumpError.
class Holder
  def keep(&b)
    @b = b
    :kept
  end

  def run
    @b.call
  end
end

def make_orphan(h)
  h.keep { return :never }
  :made
end

holder = Holder.new
p make_orphan(holder)
begin
  holder.run
rescue LocalJumpError => e
  p [:local_jump_error, e.message, e.reason]
end

# A `return` in a block at toplevel names the toplevel, so nothing after it
# runs; keep it last.
def side_effect
  puts "before the toplevel return"
end
side_effect
[1].each { return }
puts "not reached"
