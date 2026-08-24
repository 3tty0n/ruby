Warning[:experimental] = false

# Make the single-thread nesting path hot before its one-way TLS promotion.
sum = 0
5_000.times { |i| sum += i }
raise 'bad promotion warmup' unless sum == 12_497_500

expected = (0...7).map { |i| i * i }
20.times do
  ractors = (0...7).map do |i|
    Ractor.new(i) { |n| n * n }
  end
  raise 'wrong Ractor result' unless ractors.map(&:value) == expected
end

puts 'ok'
