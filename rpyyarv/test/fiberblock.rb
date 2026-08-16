# Not in the gccheck list: CRuby runs this, RPyYARV refuses it, and the refusal
# is fatal rather than rescuable since it never crosses a trampoline. A fiber
# suspends without unwinding, and both root chains RPyYARV relies on are strictly
# LIFO (the shadowstack's decr_stack, gcroots' frame list), so a block of ours
# suspended inside one unlinks roots the parent still needs. Run by hand: each
# line below must be refused by name, one run per line.

class SubFiber < Fiber; end
class DeeperFiber < SubFiber; end

# Not a Fiber, and the guard must stay out of its way.
p Array.new(2) { |i| i * 3 }

# Each of these is refused; a subclass used to slip past the identity check
# into the ifunc path, where the corruption was silent.
p DeeperFiber.new { 4 }.resume
p SubFiber.new { Fiber.yield(2); 3 }.resume
p Class.new(Fiber).new { 5 }.resume
p Fiber.new { 1 }.resume
