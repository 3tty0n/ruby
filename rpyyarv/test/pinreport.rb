# pinstat.rb dump -> {live, pinned, by_type: {type => [live, pinned]}}
require 'json'
tab = Hash.new { |h, k| h[k] = [0, 0] }
File.foreach(ARGV[0]) do |l|
  next unless l.start_with?('{"address"')
  t = l[/"type":"(\w+)"/, 1]
  t = "IMEMO/#{l[/"imemo_type":"(\w+)"/, 1]}" if t == 'IMEMO'
  tab[t][0] += 1
  tab[t][1] += 1 if l.include?('"pinned":true')
end
by_type = tab.sort_by { -_2[1] }.to_h
puts JSON.generate({ 'live' => tab.values.sum(&:first),
                     'pinned' => tab.values.sum(&:last), 'by_type' => by_type })
