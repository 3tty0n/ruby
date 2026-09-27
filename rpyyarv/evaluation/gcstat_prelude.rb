# Loaded through RUBYOPT=-r; the last at_exit hook, so it sees every GC.
if (path = ENV["RPYYARV_GCSTAT_OUT"])
  at_exit do
    s = GC.stat
    File.write(path, [s[:count], s[:major_gc_count], s[:minor_gc_count],
                      s[:time], s[:malloc_increase_bytes_limit]].join(" "))
  end
end
