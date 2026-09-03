# The nursery experiment's workload: the ruby-bench hexapdf line-wrapping
# benchmark, self-contained so `rpyyarv-jit evaluation/nursery-hexapdf.rb`
# reproduces it without scripts/bench.rb.

ROOT = File.dirname(__dir__)
RUBY_BENCH = ENV.fetch("RUBY_BENCH") { File.join(ROOT, "ruby-bench") }
BENCH_DIR = File.join(RUBY_BENCH, "benchmarks", "hexapdf")
BENCH_GEMS = ENV.fetch("BENCH_GEMS") { File.join(ROOT, ".bench-gems") }

# Same gem protocol as scripts/bench.rb's bench_gems_env.
if File.directory?(BENCH_GEMS)
  ENV["GEM_HOME"] = ENV["GEM_PATH"] = ENV["BUNDLE_PATH"] = BENCH_GEMS
  ENV["BUNDLE_APP_CONFIG"] = File.join(BENCH_GEMS, ".bundle")
  Gem.clear_paths if defined?(Gem)
end

# Iterations the bench.rb probe performs: one warm-up plus one measured.
ITERATIONS = 2
WIDTH = 50
HEIGHT = 1000
EXPECTED_SIZE = 569797

begin
  Dir.chdir(BENCH_DIR)
  # CRuby owns the RubyGems/Bundler bootstrap; see scripts/ruby-bench/harness.rb.
  previous = ENV["RPYYARV_FOREIGN_REQUIRE"]
  ENV["RPYYARV_FOREIGN_REQUIRE"] = "1"
  begin
    require "bundler"
    Bundler.setup
  ensure
    previous ? ENV["RPYYARV_FOREIGN_REQUIRE"] = previous
             : ENV.delete("RPYYARV_FOREIGN_REQUIRE")
  end

  require "hexapdf"
  require "fileutils"

  text = File.read("odyssey.txt")
  tmp = ENV.fetch("TMPDIR", "/tmp")
  ITERATIONS.times do |i|
    # Per process, so concurrent trials never share an output file.
    out = File.join(tmp, format("hexapdf-nursery-%d-%03d.pdf", Process.pid, i))
    t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    composer = HexaPDF::Composer.new(page_size: [0, 0, WIDTH, HEIGHT], margin: 0)
    composer.text(text, font_features: { kern: false }, font: "Times",
                  font_size: 10, last_line_gap: true,
                  line_spacing: { type: :fixed, value: 11.16 })
    composer.document.trailer[:ID] = %w[benchmark benchmark]
    composer.write(out, update_fields: false)
    ms = (Process.clock_gettime(Process::CLOCK_MONOTONIC) - t0) * 1000.0
    size = File.stat(out).size
    FileUtils.rm_f(out)
    raise "incorrect size #{size} (expected #{EXPECTED_SIZE})" \
      unless size == EXPECTED_SIZE

    puts "ITER #{i} #{ms} true"
  end
  puts "DONE true"
rescue Exception => e
  warn "#{e.class}: #{e.message}"
  warn e.backtrace.first(10).join("\n") if e.backtrace
  exit 1
end
