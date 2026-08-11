#!/usr/bin/env ruby
# frozen_string_literal: true

require "open3"

HERE = File.dirname(File.expand_path(__FILE__))
ROOT = File.dirname(HERE)
TOP = File.dirname(ROOT)
BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
OPTCARROT = ENV.fetch(
  "OPTCARROT_DIR",
  File.join(ROOT, "ruby-bench", "benchmarks", "optcarrot")
)
LIBVAR = RUBY_PLATFORM.include?("darwin") ? "DYLD_LIBRARY_PATH" : "LD_LIBRARY_PATH"
ROM_PATTERN = "*.{nes,NES,zip,ZIP}"

ENGINES = [
  ["cruby",       [File.join(BUILD, "ruby"), "--disable-gems"]],
  ["cruby+yjit",  [File.join(BUILD, "ruby"), "--disable-gems", "--yjit"]],
  ["cruby+zjit",  [File.join(BUILD, "ruby"), "--disable-gems", "--zjit"]],
  ["rpyyarv-jit", [File.join(ROOT, "rpyyarv-jit")]]
].freeze

def median(values)
  sorted = values.sort
  n = sorted.size
  n.odd? ? sorted[n / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
end

def supported?(command, env)
  File.executable?(command[0]) &&
    system(env, *command, "-e", "", out: File::NULL, err: File::NULL)
end

def roms_in(dir)
  Dir.glob(File.join(dir, ROM_PATTERN)).map { |path| File.expand_path(path) }.uniq.sort
end

def choose_rom
  candidates = [File.join(OPTCARROT, "examples"), Dir.pwd]
               .flat_map { |dir| roms_in(dir) }.uniq.sort

  puts "Select ROM:"
  candidates.each_with_index do |path, index|
    puts format("  %d) %s", index + 1, path)
  end
  default = candidates.index { |path| File.basename(path) == "Lan_Master.nes" } || 0
  prompt = candidates.empty? ? "ROM path: " : "number or ROM path [#{default + 1}]: "
  print prompt
  answer = $stdin.gets&.strip
  return nil unless answer
  return candidates[default] if answer.empty? && !candidates.empty?

  index = Integer(answer, exception: false)
  return candidates[index - 1] if index && index.between?(1, candidates.size)

  File.expand_path(answer)
end

def render_benchmark(summaries, engine_names)
  headers = ["ROM"] + engine_names
  table = summaries.map do |summary|
    fps_by_engine = summary[:rows].to_h { |row| [row[:name], median(row[:fps])] }
    [File.basename(summary[:rom])] + engine_names.map do |name|
      fps_by_engine[name] ? format("%.2f", fps_by_engine[name]) : "FAIL"
    end
  end
  widths = headers.each_index.map { |i| ([headers] + table).map { |row| row[i].length }.max }
  line = lambda do |row|
    row.each_with_index.map do |cell, i|
      i.zero? ? cell.ljust(widths[i]) : cell.rjust(widths[i])
    end.join("  ")
  end
  puts "\nAll ROMs (median FPS)"
  puts line.call(headers)
  puts widths.map { |width| "-" * width }.join("  ")
  table.each { |row| puts line.call(row) }
end

def run_once(command, args, env, timeout)
  argv = ["perl", "-e", "alarm shift; exec @ARGV", timeout.to_s] + command + args
  out, err, status = Open3.capture3(env, *argv)
  unless status.success?
    reason = if status.signaled? && status.termsig == Signal.list["ALRM"]
               "timeout"
             else
               "exit #{status.exitstatus || "signal #{status.termsig}"}"
             end
    detail = err.lines.map(&:strip).reject(&:empty?).last
    return [nil, nil, [reason, detail].compact.join(": ")]
  end

  fps = out[/^fps:\s+(\S+)/, 1]&.to_f
  checksum = out[/^checksum:\s+(\S+)/, 1]
  return [nil, nil, "missing fps/checksum output"] unless fps && checksum

  [fps, checksum, nil]
end

def render(rows)
  headers = ["engine", "median fps", "min", "max", "vs cruby", "checksum"]
  table = rows.map do |row|
    [row[:name], format("%.2f", median(row[:fps])),
     format("%.2f", row[:fps].min), format("%.2f", row[:fps].max),
     row[:ratio] ? format("%.2fx", row[:ratio]) : "-", row[:checksum]]
  end
  widths = headers.each_index.map { |i| ([headers] + table).map { |r| r[i].length }.max }
  line = lambda do |row|
    row.each_with_index.map do |cell, i|
      i.zero? ? cell.ljust(widths[i]) : cell.rjust(widths[i])
    end.join("  ")
  end
  puts
  puts line.call(headers)
  puts widths.map { |width| "-" * width }.join("  ")
  table.each { |row| puts line.call(row) }
end

def main(argv)
  frames = 600
  reps = 3
  timeout = 120
  rom = ENV["OPTCARROT_ROM"]
  select_rom = false
  benchmark = false

  until argv.empty?
    arg = argv.shift
    case arg
    when /\A--frames=(\d+)\z/ then frames = Regexp.last_match(1).to_i
    when "--frames" then frames = argv.shift.to_i
    when /\A--reps=(\d+)\z/ then reps = Regexp.last_match(1).to_i
    when "--reps" then reps = argv.shift.to_i
    when /\A--timeout=(\d+)\z/ then timeout = Regexp.last_match(1).to_i
    when "--timeout" then timeout = argv.shift.to_i
    when /\A--rom=(.+)\z/ then rom = Regexp.last_match(1)
    when "--rom" then rom = argv.shift.to_s
    when "--select-rom" then select_rom = true
    when "--benchmark", "--all-roms" then benchmark = true
    when "-h", "--help"
      puts "usage: optcarrot-fps.rb [ROM | --rom FILE] [--select-rom] [--benchmark] [--frames N] [--reps N] [--timeout SEC]"
      puts "  --benchmark, --all-roms  benchmark every .nes/.zip ROM in examples"
      return 0
    else
      if !arg.start_with?("-") && rom.nil?
        rom = arg
      else
        warn "unrecognized argument: #{arg}"
        return 2
      end
    end
  end

  if frames <= 0 || reps <= 0 || timeout <= 0
    warn "frames, reps and timeout must be positive"
    return 2
  end
  if benchmark && (rom || select_rom)
    warn "--benchmark cannot be combined with --rom, a positional ROM, or --select-rom"
    return 2
  end
  rom = choose_rom if !benchmark && (select_rom || (rom.nil? && $stdin.tty?))
  rom ||= File.join(OPTCARROT, "examples", "Lan_Master.nes") unless benchmark
  roms = benchmark ? roms_in(File.join(OPTCARROT, "examples")) : [rom]
  script = File.join(OPTCARROT, "bin", "optcarrot")
  unless File.file?(script) && !roms.empty? && roms.all? { |path| File.file?(path) }
    warn "optcarrot or ROM not found (optcarrot=#{OPTCARROT.inspect}, roms=#{roms.inspect})"
    return 1
  end

  extension_common = File.join(BUILD, ".ext", "common")
  zlib_bundle = Dir.glob(File.join(BUILD, ".ext", "*", "zlib.{bundle,so}")).first
  extension_arch = File.dirname(zlib_bundle) if zlib_bundle
  env = {
    LIBVAR => BUILD + File::PATH_SEPARATOR + ENV.fetch(LIBVAR, ""),
    "RUBYLIB" => [BUILD, extension_common, extension_arch, ENV["RUBYLIB"]]
                 .compact.join(File::PATH_SEPARATOR),
    "RPYYARV_BUILD" => BUILD,
    "RPYYARV_COVERAGE" => nil,
    "RPYYARV_DEBUG" => nil,
    "PYPYLOG" => nil,
    "RUBYOPT" => nil
  }
  engines = ENGINES.filter_map do |name, command|
    if supported?(command, env)
      [name, command]
    else
      puts "skip #{name}: executable or JIT option unavailable"
      nil
    end
  end
  return 1 if engines.empty?

  failed = false
  summaries = []

  roms.each_with_index do |current_rom, rom_index|
    puts "\n== #{File.basename(current_rom)} (#{rom_index + 1}/#{roms.size}) ==" if benchmark
    bench_args = [script, "--headless", "--opt", "--frames=#{frames}",
                  "--print-fps", "--print-video-checksum", current_rom]
    results = engines.to_h { |name, _| [name, { fps: [], checksums: [] }] }

    reps.times do |round|
      engines.each do |name, command|
        fps, checksum, error = run_once(command, bench_args, env, timeout)
        if error
          warn format("round %d/%d %-12s FAIL: %s", round + 1, reps, name, error)
          failed = true
          next
        end
        results[name][:fps] << fps
        results[name][:checksums] << checksum
        puts format("round %d/%d %-12s %8.2f fps  checksum=%s",
                    round + 1, reps, name, fps, checksum)
      end
    end

    rows = engines.filter_map do |name, _|
      result = results[name]
      next if result[:fps].empty?
      checksums = result[:checksums].uniq
      failed = true if checksums.size != 1 || result[:fps].size != reps
      { name: name, fps: result[:fps], checksum: checksums.join("/") }
    end
    baseline = rows.find { |row| row[:name] == "cruby" }
    base_fps = baseline && median(baseline[:fps])
    rows.each { |row| row[:ratio] = base_fps && median(row[:fps]) / base_fps }
    render(rows) unless benchmark
    summaries << { rom: current_rom, rows: rows }

    all_checksums = rows.map { |row| row[:checksum] }.uniq
    if all_checksums.size != 1
      warn "\nFAILED: checksum mismatch across engines for #{File.basename(current_rom)}"
      failed = true
    elsif !benchmark
      puts "\n#{frames} frames, median of #{reps} runs; all checksums=#{all_checksums.first}"
    end
  end

  render_benchmark(summaries, engines.map(&:first)) if benchmark
  puts "\n#{roms.size} ROMs, #{frames} frames, median of #{reps} runs" if benchmark
  failed ? 1 : 0
end

exit(main(ARGV)) if __FILE__ == $PROGRAM_NAME
