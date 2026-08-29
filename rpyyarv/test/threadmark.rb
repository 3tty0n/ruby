# A GC on a second Ruby thread runs the mark hook off the main thread.
worker = eval('Thread.new { 100_000.times { "x" * 64 }; :done }')
total = 0
20_000.times { |i| total += format("%d", i).size }
puts worker.value
puts total
