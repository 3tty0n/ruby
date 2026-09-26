# -r'd into every engine by the compaction stress run: every major GC
# compacts, and a timer thread forces the most aggressive compaction while
# the main thread is inside a delegated host call.
GC.auto_compact = true
Thread.new do
  loop do
    sleep 0.02
    GC.verify_compaction_references(expand_heap: true, toward: :empty)
  end
end
