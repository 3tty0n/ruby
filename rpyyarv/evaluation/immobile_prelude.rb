# -r'd by evaluation/immobile.rb.  At exit: compact (CRuby records pins
# only during a compacting collection, and keeps the bits until the next
# major mark), then count the pinned objects and report heap density.
require "objspace"
require "tempfile"
at_exit do
  before = GC.stat(:heap_allocated_pages)
  GC.compact
  st = GC.stat
  slots = GC.stat_heap.values.sum { |h| h[:heap_eden_slots] }
  moved = GC.latest_compact_info[:moved].values.sum
  pinned = pinned_bytes = 0
  types = Hash.new(0)
  Tempfile.create("immobile") do |f|
    ObjectSpace.dump_all(output: f)
    f.flush
    File.foreach(f.path) do |l|
      next unless l.include?('"pinned":true')
      pinned += 1
      pinned_bytes += l[/"memsize":(\d+)/, 1].to_i
      types[l[/"type":"(\w+)"/, 1]] += 1
    end
  end
  top = types.sort_by { -_2 }.first(4).map { |t, n| "#{t}:#{n}" }.join("/")
  $stderr.puts "IMMOBILE pinned=#{pinned} pinned_bytes=#{pinned_bytes} " \
               "live=#{st[:heap_live_slots]} slots=#{slots} " \
               "pages_before=#{before} pages=#{st[:heap_allocated_pages]} " \
               "moved=#{moved} types=#{top}"
end
