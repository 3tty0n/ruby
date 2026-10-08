def bench_now_ns
  Process.clock_gettime(Process::CLOCK_MONOTONIC, :nanosecond)
end