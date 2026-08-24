Warning[:experimental] = false

expected = (0...7).map { |i| i * i }
20.times do
  ractors = (0...7).map do |i|
    Ractor.new(i) { |n| n * n }
  end
  raise 'wrong Ractor result' unless ractors.map(&:value) == expected
end

puts 'ok'
