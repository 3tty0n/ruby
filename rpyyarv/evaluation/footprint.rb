#!/usr/bin/env ruby
# frozen_string_literal: true

# Physical footprint at the end of a run, split into components that sum
# to it: vmmap's per-region dirty+swapped bytes, each region given to one
# component, with the host's and the framework's own accounting carving
# the malloc and anonymous-VM regions.  One niced process at a time.
#
#   ruby evaluation/footprint.rb --out DIR [--suite all|awfy|ruby-bench]
#        [--filter NAME ...] [--engine NAME ...] [--dump NAME ...]
#   ruby evaluation/footprint.rb --report DIR/footprint.jsonl
#
# --dump NAME also dumps the host heap of NAME under cruby and rpyyarv-jit
# (with RPYYARV_COVERAGE=1 for its root inventory) for retention.rb.

require "fileutils"
require "json"
require "optparse"
require "tempfile"

module Footprint
  HERE = File.dirname(File.expand_path(__FILE__))
  ROOT = File.expand_path("..", HERE)
  PRELUDE = File.join(HERE, "footprint_prelude.rb")
  BIN = ENV.fetch("RPYYARV_BIN_DIR", ROOT)
  ENGINES = %w[cruby cruby+yjit rpyyarv rpyyarv-jit].freeze
  PYPYLOG = "gc-minor,gc-collect-done,gc-set-nursery-size,jit-backend-addr"
  ARENA = 512 * 1024
  COMPONENTS = %w[cruby_heap rpython_heap jit_code jit_meta
                  malloc_other vm_other image_self image_libruby image_other
                  stack other].freeze

  module_function

  def engines
    b = ->(n) { File.join(BIN, n) }
    { "cruby" => [File.join(BUILD, "ruby"), "--disable-gems"],
      "cruby+yjit" => [File.join(BUILD, "ruby"), "--disable-gems", "--yjit"],
      "rpyyarv" => [b["rpyyarv"]], "rpyyarv-jit" => [b["rpyyarv-jit"]] }
  end

  def bytes(s)
    n = s.to_f
    case s[-1]
    when "K" then n * 1024
    when "M" then n * 1_048_576
    when "G" then n * 1_073_741_824
    else n
    end.round
  end

  REGION = /^(.+?)\s+(\h+|kernel)-(\h+|kernel)\s+\[\s*(\S+)\s+(\S+)\s+(\S+)\s+
            (\S+)\]\s+\S+\s+SM=\S+\s*(.*)$/x

  # Two vmmap sections (non-writable, writable) list disjoint regions.
  def parse_vmmap(text)
    regions = text.each_line.filter_map do |l|
      m = REGION.match(l) or next
      { type: m[1].strip, start: m[2].to_i(16), stop: m[3].to_i(16),
        resident: bytes(m[5]), footprint: bytes(m[6]) + bytes(m[7]),
        detail: m[8].strip }
    end
    { regions: regions,
      footprint: text[/^Physical footprint:\s+(\S+)/, 1]&.then { bytes(_1) },
      footprint_peak:
        text[/^Physical footprint \(peak\):\s+(\S+)/, 1]&.then { bytes(_1) } }
  end

  def parse_pypylog(text)
    used = text.scan(/total memory used: (\d+)/).flatten.map(&:to_i)
    code = text.scan(/has address (0x\h+) to (0x\h+)/)
               .map { |a, b| [a.hex, b.hex] }
    { nursery: text.scan(/nursery size: (\d+)/).flatten.last.to_i,
      used_last: used.last.to_i, used_peak: used.max.to_i,
      arenas_last: text.scan(/arenas:\s+\d+\s+=>\s+(\d+)/).last&.first.to_i,
      raw_last: text.scan(/raw-malloced:\s+\d+\s+=>\s+(\d+)/).last&.first.to_i,
      code: code }
  end

  # Arenas are freed only by a major collection, so the count after the
  # last one bounds the arena bytes below; minor logs give the total used.
  def rpython_resident(py)
    return 0 if py[:nursery].zero?

    py[:nursery] + [py[:arenas_last] * ARENA + py[:raw_last],
                    py[:used_last]].max
  end

  def parse_stats(text)
    text.each_line.to_h { |l| k, v = l.split; [k, v.to_i] }
  end

  # Every region goes to exactly one bucket; carving never exceeds a bucket,
  # so a component overestimate shows up as a smaller residual, not a sum
  # beyond the footprint.
  def attribute(vm, st, py, exe)
    code_regions = vm[:regions].select do |r|
      r[:type].start_with?("VM_ALLOCATE") &&
        py[:code].any? { |a, _| a >= r[:start] && a < r[:stop] }
    end
    bucket = Hash.new(0)
    vm[:regions].each do |r|
      key = if code_regions.include?(r) then :jit_code
            elsif r[:type].start_with?("MALLOC") then :malloc
            elsif r[:type].start_with?("VM_ALLOCATE") then :vm
            elsif r[:type] =~ /stack/i then :stack
            elsif r[:type].start_with?("__") || r[:type].include?("shlib")
              if r[:detail] == exe then :image_self
              elsif r[:detail].include?("libruby") then :image_libruby
              else :image_other
              end
            else :other
            end
      bucket[key] += r[:footprint]
    end
    carve = lambda do |from, want|
      take = [[want.to_i, 0].max, bucket[from]].min
      bucket[from] -= take
      take
    end
    c = {}
    c["cruby_heap"] = carve[:vm, st["heap_page_bytes"]]
    c["jit_code"] = bucket.delete(:jit_code).to_i +
                    carve[:vm, st["yjit_code_region_size"]]
    c["vm_other"] = bucket.delete(:vm).to_i
    c["jit_meta"] = carve[:malloc, st["yjit_alloc_size"]]
    c["rpython_heap"] = carve[:malloc, rpython_resident(py)]
    c["malloc_other"] = bucket.delete(:malloc).to_i
    %i[image_self image_libruby image_other stack other].each do |k|
      c[k.to_s] = bucket.delete(k).to_i
    end
    c
  end

  # SIGALRM does not reliably stop an rpyyarv process; a kill loop does.
  def run(argv, env, out, timeout)
    pid = Process.spawn(env, *argv, out: out, err: [:child, :out],
                        pgroup: true)
    deadline = Time.now + timeout
    loop do
      return $?.success? if Process.waitpid(pid, Process::WNOHANG)
      if Time.now > deadline
        Process.kill(:KILL, -pid)
        Process.waitpid(pid)
        return false
      end
      sleep 0.5
    end
  end

  def measure(ename, argv, script, env, raw, timeout)
    rpy = ename.start_with?("rpyyarv")
    env = env.merge("FOOTPRINT_OUT" => raw,
                    "RUBYLIB" => [uninstalled_rubylib, env["RUBYLIB"]]
                                   .compact.join(File::PATH_SEPARATOR))
    env["PYPYLOG"] = "#{PYPYLOG}:#{raw}.pypylog" if rpy
    t0 = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    ok = run(["nice", "-n", "19", "/usr/bin/time", "-l", *argv,
              "-r", PRELUDE, script], env, "#{raw}.out", timeout)
    secs = Process.clock_gettime(Process::CLOCK_MONOTONIC) - t0
    row = { "engine" => ename, "seconds" => secs.round(1) }
    out = File.read("#{raw}.out").scrub
    row["maxrss"] = out[/(\d+)\s+maximum resident set size/, 1]&.to_i
    row["peak_footprint"] = out[/(\d+)\s+peak memory footprint/, 1]&.to_i
    row.merge!("raw" => raw, "exe" => File.realpath(argv[0]))
    return row.merge("status" => "FAIL") unless ok

    row.merge(analyse(row))
  end

  # From the raw files alone, so a report can re-attribute old runs.
  def analyse(row)
    raw = row["raw"]
    return { "status" => "FAIL" } unless File.exist?("#{raw}.vmmap") &&
                                         File.exist?("#{raw}.stats")

    vm = parse_vmmap(File.read("#{raw}.vmmap"))
    return { "status" => "FAIL" } unless vm[:footprint]

    st = parse_stats(File.read("#{raw}.stats"))
    log = "#{raw}.pypylog"
    py = parse_pypylog(File.exist?(log) ? File.read(log) : "")
    { "status" => "ok", "footprint" => vm[:footprint],
      "footprint_vmmap_peak" => vm[:footprint_peak],
      "region_sum" => vm[:regions].sum { _1[:footprint] },
      "components" => attribute(vm, st, py, row["exe"]), "host" => st,
      "msl" => msl_classes("#{raw}.m.msl"),
      "rpython" => py.except(:code).merge(
        "resident" => rpython_resident(py),
        "code_bytes" => py[:code].sum { |a, b| b - a },
        "loops" => py[:code].size) }
  end

  # Live bytes by the innermost non-allocator frame's image: libruby's are
  # the host's, the binary's pypy_g_* are RPython's, rpyyarv_* the shim's.
  def msl(ename, argv, script, env, raw, timeout)
    env = env.merge("FOOTPRINT_OUT" => "#{raw}.m",
                    "MallocStackLogging" => "lite",
                    "RUBYLIB" => [uninstalled_rubylib, env["RUBYLIB"]]
                                   .compact.join(File::PATH_SEPARATOR))
    run(["nice", "-n", "19", *argv, "-r", PRELUDE, script], env,
        "#{raw}.msl.out", timeout)
  end

  MSL_NODE = /^ +[+!: ]*?(\d+) \(([\d.]+ ?\w*)\) (.+?)  \(in ([^)]+)\)/
  ALLOCATOR = /^lib(system_\w+|c\+\+|c\+\+abi)[.\d]*\.dylib/

  # Inverted call tree: a node is a leaf frame, its children its callers;
  # below allocator frames, the first other frame is the allocation site.
  def msl_classes(path)
    return nil unless File.exist?(path)

    skip = nil
    File.foreach(path).each_with_object(Hash.new(0)) do |l, h|
      m = MSL_NODE.match(l) or next
      depth = l.index(/\d/)
      next if skip && depth > skip

      skip = nil
      next if m[4].match?(ALLOCATOR)

      h[msl_class(m[3], m[4])] += bytes(m[2].sub(" bytes", ""))
      skip = depth
    end
  end

  def msl_class(fn, image)
    if image.start_with?("libruby")
      return "cruby_heap" if fn.include?("heap_page_allocate")
      return "jit_meta" if fn.include?("alloc::") || fn.include?("yjit")

      "cruby_malloc"
    elsif image.start_with?("rpyyarv")
      case fn
      when /MiniMark|ArenaCollection|frameworkgc/ then "rpython_heap"
      when /AsmMemoryManager|MachineDataBlock|^pypy_g_alloc_\d+$/
        "jit_code"
      when /^pypy_/ then "rpython_raw"
      else "shim"
      end
    else
      "other"
    end
  end

  def dump(ename, argv, script, env, raw, timeout)
    env = env.merge("FOOTPRINT_OUT" => "#{raw}.d",
                    "FOOTPRINT_DUMP" => "#{raw}.heap.json",
                    "RUBYLIB" => [uninstalled_rubylib, env["RUBYLIB"]]
                                   .compact.join(File::PATH_SEPARATOR))
    env["RPYYARV_COVERAGE"] = "1" if ename.start_with?("rpyyarv")
    run(["nice", "-n", "19", *argv, "-r", PRELUDE, script], env,
        "#{raw}.dump.out", timeout)
  end

  def main(argv)
    opts = { suite: "all", filters: [], engines: [], dumps: [], msl: [] }
    OptionParser.new do |o|
      o.on("--out DIR") { |v| opts[:out] = v }
      o.on("--suite NAME") { |v| opts[:suite] = v }
      o.on("--filter NAME") { |v| opts[:filters] << v }
      o.on("--engine NAME") { |v| opts[:engines] << v }
      o.on("--dump NAME") { |v| opts[:dumps] << v }
      o.on("--msl NAME") { |v| opts[:msl] << v }
      o.on("--report FILE") { |v| opts[:report] = v }
    end.parse!(argv)
    return report(opts[:report]) if opts[:report]
    abort "--out is required" unless opts[:out]

    load File.join(ROOT, "scripts", "bench.rb") unless defined?(AwfySuite)
    rawdir = File.join(opts[:out], "raw")
    FileUtils.mkdir_p(rawdir)
    jsonl = File.open(File.join(opts[:out], "footprint.jsonl"), "a")
    names = opts[:engines].empty? ? ENGINES : opts[:engines]
    eng = engines.slice(*names)
    emit = lambda do |row|
      jsonl.puts JSON.generate(row)
      jsonl.flush
      warn format("%s/%s %s fp=%.1fM", row["benchmark"], row["engine"],
                  row["status"], row["footprint"].to_f / 1_048_576)
    end
    Tempfile.create(["footprint_empty", ".rb"]) do |f|
      eng.each do |ename, eargv|
        raw = File.join(rawdir, "__startup__.#{ename}")
        emit[{ "suite" => "startup", "benchmark" => "__startup__" }
             .merge(measure(ename, eargv, f.path, base_env, raw, 60))]
      end
    end
    suites = { "all" => %w[awfy ruby-bench], "awfy" => %w[awfy],
               "ruby-bench" => %w[ruby-bench] }.fetch(opts[:suite])
    suites.each do |sname|
      suite = sname == "awfy" ? AwfySuite.new(opts) : RubyBenchSuite.new(opts)
      next unless suite.available?

      suite.benchmarks.each do |bench|
        next unless opts[:filters].empty? ||
                    opts[:filters].any? { |x| bench == x }

        eng.each do |ename, eargv|
          # nbody is in both suites: the suite keeps their files apart.
          raw = File.join(rawdir, "#{suite.name}.#{bench}.#{ename}")
          row = { "suite" => suite.name, "benchmark" => bench }
          suite.with_script(bench) do |script, env, _|
            row.merge!(measure(ename, eargv, script, env, raw, suite.timeout))
            if opts[:dumps].include?(bench) &&
               %w[cruby rpyyarv-jit].include?(ename)
              row["dump"] = dump(ename, eargv, script, env, raw, suite.timeout)
            end
            if opts[:msl].include?(bench)
              row["msl"] = msl(ename, eargv, script, env, raw, suite.timeout)
            end
          end
          emit[row]
        end
      end
    end
    jsonl.close
    0
  end

  def mb(b) = b ? format("%.1f", b / 1_048_576.0) : "-"

  # Per benchmark and engine: footprint and its components (MB), then the
  # decomposition of rpyyarv(-jit)'s excess over cruby and cruby+yjit.
  def report(path)
    rows = File.readlines(path).map { JSON.parse(_1) }
                .select { _1["status"] == "ok" }
                .map { _1.merge(analyse(_1)) }
                .select { _1["status"] == "ok" }
    by = rows.group_by { "#{_1['suite']}/#{_1['benchmark']}" }
             .transform_values { |a| a.to_h { [_1["engine"], _1] } }
    puts (%w[benchmark engine maxrss peak_fp fp region_sum] + COMPONENTS +
          %w[residual]).join(",")
    by.each do |bench, es|
      es.each do |e, r|
        c = r["components"]
        puts ([bench, e, mb(r["maxrss"]), mb(r["peak_footprint"]),
               mb(r["footprint"]), mb(r["region_sum"])] +
              COMPONENTS.map { mb(c[_1]) } +
              [mb(r["footprint"] - c.values.sum)]).join(",")
      end
    end
    msl = %w[cruby_heap cruby_malloc jit_code jit_meta rpython_heap
             rpython_raw shim other]
    puts
    puts (%w[benchmark engine malloc_stacks] + msl).join(",")
    rows.select { _1["msl"] }.each do |r|
      puts ([r["benchmark"], r["engine"], mb(r["msl"].values.sum)] +
            msl.map { mb(r["msl"][_1]) }).join(",")
    end
    puts
    puts (%w[benchmark engine base extra] + COMPONENTS).join(",")
    by.each do |bench, es|
      %w[rpyyarv rpyyarv-jit].product(%w[cruby cruby+yjit]).each do |e, b|
        next unless es[e] && es[b]

        c = es[e]["components"]
        d = es[b]["components"]
        puts ([bench, e, b, mb(es[e]["footprint"] - es[b]["footprint"])] +
              COMPONENTS.map { mb(c[_1] - d[_1]) }).join(",")
      end
    end
    0
  end
end

exit Footprint.main(ARGV) if $PROGRAM_NAME == __FILE__
