t0 = bench_now_ns
t1 = bench_now_ns
puts t0 > 0
puts t1 >= t0
puts "#{t1 - t0}".to_i >= 0
__END__
true
true
true