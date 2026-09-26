# R1: when the host frees an owner object (a block-handle owner TypedData,
# or a Fiber), RPyYARV releases the framework root it names (a handle-table
# slot, a saved fiber state) only at a later drain -- the next handle
# allocation, or the next fiber creation -- and the framework's own
# collector then reclaims the framework state behind it.
#
# Runs under plain CRuby too: without RPyYARV.r1_stats it prints only the
# host-side columns (the framework ones are left blank).
#
#   rpyyarv-jit-r1 test/r1rounds.rb [rounds] [k] [--no-drain]
#
# --no-drain is the negative control: it skips the one allocation each
# round that would drain the dead-handle queue / reap dead fiber states,
# so the pending queue should hold entries instead of falling back to zero.

ROUNDS = (ARGV[0] || 10).to_i
K = (ARGV[1] || 2_000).to_i
SUPPRESS_DRAIN = ARGV.include?("--no-drain")

HOOK = begin
  defined?(RPyYARV) ? (RPyYARV.r1_stats; true) : false
rescue NoMethodError, NameError
  false
end

def host_counts
  procs = 0; fibers = 0; enums = 0
  ObjectSpace.each_object(Proc) { procs += 1 }
  ObjectSpace.each_object(Fiber) { fibers += 1 }
  ObjectSpace.each_object(Enumerator) { enums += 1 }
  [procs, fibers, enums]
end

def frame_stats
  HOOK ? RPyYARV.r1_stats : [nil, nil, nil, nil, nil]
end

def frame_collect!
  RPyYARV.r1_collect! if HOOK
end

# (a) a Proc passed to a host C method (Hash#store) that keeps it only in a
# host object (the Hash), which is then dropped.
def churn_hash_procs(k)
  k.times do |i|
    blk = Proc.new { i }
    h = {}
    h.store(:p, blk)
  end
end

# (b) a Proc cycle: the block closes back over the local naming the Proc.
def churn_proc_cycles(k)
  k.times do
    p = nil
    p = Proc.new { p }
  end
end

# (c) a Fiber suspended mid-body, whose frames refer back to it.
def churn_fibers(k)
  k.times do
    fiber = nil
    fiber = Fiber.new { fiber; Fiber.yield }
    fiber.resume
  end
end

# (d) an Enumerator suspended via #next (a Fiber under the hood).
def churn_enumerators(k)
  k.times do
    e = [1, 2, 3].each
    e.next
  end
end

# The drain triggers R1 names: one more handle allocation, one more fiber
# creation (its first resume is what reaps dead registry entries).
def drain!
  return if SUPPRESS_DRAIN
  blk = Proc.new { }
  h = {}
  h.store(:p, blk)
  Fiber.new { }.resume
end

base_host = host_counts
base_frame = frame_stats

puts %w[round proc_delta fiber_delta enum_delta live_handles table_len
        dead_queue live_fibers heap_bytes].join(",")

ROUNDS.times do |r|
  churn_hash_procs(K)
  churn_proc_cycles(K)
  churn_fibers(K)
  churn_enumerators(K)

  GC.start(full_mark: true, immediate_sweep: true)
  GC.start(full_mark: true, immediate_sweep: true)
  drain!
  frame_collect!

  # Read the frame side first: ObjectSpace.each_object below hands a block
  # to a host method, which is itself a handle allocation and would drain
  # the queue we are trying to observe.
  fh, ft, fq, ff, fb = frame_stats
  hp, hf, he = host_counts
  puts [r + 1, hp - base_host[0], hf - base_host[1], he - base_host[2],
        fh, ft, fq, ff, fb].join(",")
end

warn "hook: #{HOOK ? "present" : "absent (host facts only)"}"
warn "suppress_drain: #{SUPPRESS_DRAIN}"
warn "base_host: #{base_host.inspect}"
warn "base_frame: #{base_frame.inspect}" if HOOK
