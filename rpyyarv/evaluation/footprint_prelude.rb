# -r'd by evaluation/footprint.rb.  At exit, after the benchmark's own
# at_exit hooks: the host's view of its heap, then a vmmap of this process,
# both under $FOOTPRINT_OUT; with $FOOTPRINT_DUMP, a full GC and a heap dump;
# with MallocStackLogging, live allocations by allocating function.
require "objspace"
at_exit do
  out = ENV.fetch("FOOTPRINT_OUT")
  st = GC.stat
  slot_bytes = GC.stat_heap.values.sum do |h|
    h[:heap_live_slots] * h[:slot_size]
  end
  yjit = defined?(RubyVM::YJIT) && RubyVM::YJIT.enabled? ?
    RubyVM::YJIT.runtime_stats : {}
  stats = {
    "heap_live_slots" => st[:heap_live_slots],
    "heap_allocated_pages" => st[:heap_allocated_pages],
    "heap_page_bytes" => st[:heap_allocated_pages] *
      GC::INTERNAL_CONSTANTS[:HEAP_PAGE_SIZE],
    "live_slot_bytes" => slot_bytes,
    "memsize_of_all" => ObjectSpace.memsize_of_all,
    "malloc_increase_bytes" => st[:malloc_increase_bytes],
    "oldmalloc_increase_bytes" => st[:oldmalloc_increase_bytes],
    "yjit_code_region_size" => yjit[:code_region_size],
    "yjit_alloc_size" => yjit[:yjit_alloc_size],
  }
  File.write("#{out}.stats", stats.map { |k, v| "#{k} #{v.to_i}\n" }.join)
  # Orphaned, so vmmap's own RSS never joins this process's rusage maxrss.
  system("sh", "-c", "(vmmap -wide #{Process.pid} > '#{out}.tmp' " \
         "2>/dev/null; mv '#{out}.tmp' '#{out}.vmmap') &")
  sleep 0.1 until File.exist?("#{out}.vmmap")
  if ENV["MallocStackLogging"]
    system("sh", "-c", "(malloc_history #{Process.pid} -callTree " \
           "-invert -ignoreThreads > '#{out}.tmp' 2>&1; " \
           "mv '#{out}.tmp' '#{out}.msl') &")
    sleep 0.1 until File.exist?("#{out}.msl")
  end
  if (dump = ENV["FOOTPRINT_DUMP"])
    GC.start
    File.open(dump, "w") { |f| ObjectSpace.dump_all(output: f) }
  end
end
