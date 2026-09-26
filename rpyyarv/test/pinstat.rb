# RUBYOPT=-r prelude: at exit, compact and dump the heap to $PINSTAT_OUT.
# Pin bits survive a compaction until the next full mark, so the dump
# says which live objects that compaction could not move.
require 'objspace'
at_exit do
  GC.compact
  File.open(ENV.fetch('PINSTAT_OUT'), 'w') do |f|
    ObjectSpace.dump_all(output: f)
  end
end
