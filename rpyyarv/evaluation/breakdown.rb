#!/usr/bin/env ruby
# frozen_string_literal: true

# Where rpyyarv-jit's wall time goes: macOS `sample` stacks, one bucket each.
# Attribution rule, per sample of the main thread (the innermost owner wins):
#   1. a CRuby or RPython GC frame anywhere: the innermost of them (gc)
#   2. else a tracer, optimizer or backend frame anywhere: compile
#   3. else the leafmost non-system frame decides: libruby or shim C code is
#      delegated CRuby, JIT code is compiled code, and an RPython frame looks
#      rootward for JIT code (a residual call from a trace) or the portal,
#      blackhole or a CRuby frame (T interpreting outside traces).
# Unwinding stops at JIT code: the aarch64 backend keeps the jitframe in x29.

require "fileutils"
require "json"
require "open3"
require "optparse"

module Breakdown
  HERE = File.dirname(File.expand_path(__FILE__))
  ROOT = File.expand_path("..", HERE)

  BUCKETS = %w[interp trace compile cruby cruby_gc rpython_gc
               unattributed].freeze
  # Internals too, not just entry points: a stack cut by a tail call keeps
  # only its leaf.
  CRUBY_GC = /\A(gc_|garbage_collect|rb_gc_(obj_free|mark|impl_start|
                 impl_garbage_collect|start\z)|rb_gc\z|rb_\w+_mark_and_move\z)/x
  RPYTHON_GC = /\Apypy_g_(IncrementalMiniMarkGC_|ArenaCollection_|
                          _?trace\w*__gc_callback|collect_and_reserve|
                          AddressStack_|AddressDeque_)/x
  # Any tracer, optimizer or backend frame: the entry often is not visible.
  COMPILE = /\Apypy_g_(MetaInterp_|MIFrame_|Trace_|TraceIterator_|Optimiz|
                       Opt[A-Z]|IntBound|HeapCache|Regalloc|RegisterManager|
                       \w*Assembler\w*_|AbstractAarch64Builder_|\w*ResOp\w*_|
                       ResOperation|ResumeDataLoopMemo|ResumeDataBoxReader|
                       compile_and_run_once|send_(loop|bridge)_to_backend|
                       compile_|rpython_jit_metainterp_(pyjitpl|optimizeopt|
                       opencoder|compile|history|resoperation))/x
  BLACKHOLE = /\Apypy_g_(BlackholeInterpreter_|resume_in_blackhole|
                         blackhole_from_resumedata|_run_forever|
                         ResumeDataDirectReader_|AbstractResumeGuardDescr_|
                         JitCode_)/x
  PORTAL = /\Apypy_g_(portal|ll_portal_runner)/
  DISPATCH = /\A(rb_funcall|rb_call0|vm_call0|vm_exec|rb_vm_invoke|rb_yield|
                 vm_invoke|rb_method_call|invoke_block|rpyyarv_funcall|
                 rpyyarv_call)/x

  MACHINERY = /\A(rb_funcall|rb_call0|vm_call0|rb_protect|rpyyarv_|
                  rb_current_ec|vm_push_frame|rb_vm_pop_frame|rb_ec_|vm_call_|
                  rb_callable_method_entry|callable_method_entry|
                  search_method|rb_method_basic_definition|cached_callable|
                  rb_check_funcall|check_funcall|method_entry_resolve|
                  rb_vm_frame|vm_passed_block|rb_block_given|rb_keyword_given|
                  rb_class_new_instance|rb_obj_call_init|rb_ensure|
                  rb_add_method|\w*_body\z)/x

  module_function

  # [[frames leaf-first, self samples], ...] for the main thread.
  def parse_sample(path)
    return [] unless File.exist?(path)

    lines = File.readlines(path, chomp: true)
    start = lines.index { |l| l.include?("Thread_") && l.include?("main-") }
    return [] unless start

    base = lines[start].index(/\d/)
    path_stack = []
    nodes = []
    lines[(start + 1)..].each do |line|
      col = line.index(/\d/)
      break if line.strip.empty? || col.nil? || col <= base

      m = line[col..].match(/\A(\d+) (.*)\z/) or break
      depth = (col - base) / 2
      path_stack = path_stack.first(depth - 1)
      node = { count: m[1].to_i, frame: frame_of(m[2]), kids: 0 }
      parent = path_stack.last
      parent[:kids] += node[:count] if parent
      path_stack << node
      node[:path] = path_stack.map { |n| n[:frame] }
      nodes << node
    end
    nodes.filter_map do |n|
      self_count = n[:count] - n[:kids]
      [n[:path].reverse, self_count] if self_count.positive?
    end
  end

  def frame_of(text)
    name = text[/\A(.*?)\s+\(in /, 1] || text
    mod = text[/\(in (.*?)\)/, 1] || ""
    addr = text[/\[0x(\h+)\]/, 1]
    [name.sub(/\A_/, ""), mod, addr && addr.to_i(16)]
  end

  def kind(frame, exe)
    name, mod, = frame
    return :jit if mod == "<unknown binary>"
    return name.match?(CRUBY_GC) ? :cgc : :cruby if mod.start_with?("libruby")
    return :sys unless mod == exe
    # mark_roots itself is inlined into the shim's hook; _mark_all is the walk.
    return :root if name.match?(/\Apypy_g__?mark_(roots|all)\b/)
    return :rgc if name.match?(RPYTHON_GC)
    return :compile if name.match?(COMPILE)
    return :blackhole if name.match?(BLACKHOLE)
    return :portal if name.match?(PORTAL)
    return :t if name.start_with?("pypy_g_", "RPy", "pypy_", "LL_", "_RPy")

    :glue
  end

  # Returns [bucket, detail]; detail names the sub-bucket.
  def classify(frames, exe)
    kinds = frames.map { |f| kind(f, exe) }
    gc_at = kinds.index { |k| k == :cgc || k == :rgc }
    if gc_at
      return ["rpython_gc", "rpython_gc"] if kinds[gc_at] == :rgc
      inner = kinds[0...kinds.rindex(:cgc)]
      return ["cruby_gc", "root_walk"] if inner.include?(:root)
      return ["cruby_gc", "rpyyarv_mark"] if (inner & %i[t glue]).any?

      return ["cruby_gc", "cruby_gc"]
    end
    return ["compile", "compile"] if kinds.include?(:compile)

    first = kinds.index { |k| k != :sys }
    return ["unattributed", "no_frame"] unless first

    case kinds[first]
    when :jit then ["trace", "jit_code"]
    when :cruby, :glue then boundary(frames, kinds, first)
    else rpython_owner(kinds, first)
    end
  end

  # dispatch splits into the send machinery's own frames (leaf is one of
  # them), a delegated ISeq in CRuby's interpreter, and the callee's C work.
  def boundary(frames, kinds, first)
    stop = kinds.index.with_index do |k, i|
      i > first && %i[t portal jit blackhole compile].include?(k)
    end
    seg = frames[first...(stop || frames.size)]
    return ["cruby", "c_helper"] unless seg.any? { |n, | n.match?(DISPATCH) }
    return ["cruby", "vm_exec"] if seg.any? { |n, | n.start_with?("vm_exec") }
    return ["cruby", "send_machinery"] if seg[0][0].match?(MACHINERY)

    ["cruby", "callee"]
  end

  def rpython_owner(kinds, first)
    kinds[first..].each do |k|
      case k
      when :jit then return ["trace", "residual_call"]
      when :portal then return ["interp", "portal"]
      when :blackhole then return ["interp", "blackhole"]
      when :cruby, :glue then return ["interp", "under_cruby"]
      end
    end
    ["interp", "outside_portal"]
  end

  def jit_ranges(log)
    return [] unless log && File.exist?(log)

    File.read(log).scan(
      /^(Loop|bridge) .* has address 0x(\h+) to 0x(\h+)/i
    ).map { |k, a, b| [k.downcase, a.to_i(16), b.to_i(16)] }
  end

  def jit_region(frames, ranges)
    addr = frames.find { |_, mod, _| mod == "<unknown binary>" }&.last
    return "stub" unless addr

    hit = ranges.reverse_each.find { |_, a, b| addr >= a && addr < b }
    hit ? hit[0] : "stub"
  end

  def summarize(path, exe, ranges = [])
    buckets = Hash.new(0)
    details = Hash.new(0)
    leaves = Hash.new { |h, k| h[k] = Hash.new(0) }
    entries = Hash.new(0)
    regions = Hash.new(0)
    total = 0
    parse_sample(path).each do |frames, n|
      bucket, detail = classify(frames, exe)
      total += n
      buckets[bucket] += n
      details["#{bucket}/#{detail}"] += n
      leaf = frames.find { |f| kind(f, exe) != :sys } || frames.first
      leaves[bucket][leaf ? leaf[0] : "?"] += n
      regions[jit_region(frames, ranges)] += n if bucket == "trace"
      next unless bucket == "cruby"

      entry = frames.reverse.find { |f| %i[cruby glue].include?(kind(f, exe)) }
      entries[entry[0]] += n if entry
    end
    { "samples" => total, "buckets" => buckets, "details" => details,
      "jit_regions" => regions, "cruby_entries" => top(entries, 15),
      "top_leaves" => leaves.transform_values { |h| top(h, 12) } }
  end

  def top(hash, n)
    hash.sort_by { |_, v| -v }.first(n).to_h
  end

  def load_bench
    load File.join(ROOT, "scripts", "bench.rb") unless defined?(RubyBenchSuite)
  end

  # Line-buffered, with CRuby's GC clock on every ITER line for a cross-check.
  def instrument(script)
    src = File.read(script)
    src.sub!('puts "ITER " + n.to_s + " " + ms.to_s + " true"',
             'puts "ITER " + n.to_s + " " + ms.to_s + " true " + ' \
             'GC.stat(:time).to_s + " " + GC.count.to_s')
    File.write(script, "$stdout.sync = true\n" + src)
  end

  def sampler(pid, secs, file)
    r, w = IO.pipe
    spid = spawn("sample", pid.to_s, secs.to_s, "1", "-mayDie",
                 "-file", file, out: w, err: w)
    w.close
    marks = {}
    thread = Thread.new do
      r.each_line do |l|
        now = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        marks[:start] ||= now if l.start_with?("Sampling process")
        marks[:stop] ||= now if l.start_with?("Sampling completed")
      end
    end
    [spid, thread, marks]
  end

  # :warmup samples launch to WARMED, then stops the child; :steady samples
  # a window from WARMED. Never both: symbolicating one delays the other.
  def run_one(suite, exe, bench, dir, window, tag, phase)
    lines = []
    samples = {}
    suite.with_script(bench) do |script, env, _warm|
      instrument(script)
      log = File.join(dir, "#{tag}.pypylog")
      child_env = env.merge(
        "MIN_BENCH_TIME" => (window * 3).to_s,
        "PYPYLOG" => "jit-summary,jit-backend-addr:#{log}"
      )
      r, w = IO.pipe
      pid = spawn(child_env, exe, script, out: w,
                                          err: File.join(dir, "#{tag}.stderr"))
      w.close
      file = File.join(dir, "#{tag}.#{phase}.sample.txt")
      s = phase == :warmup ? sampler(pid, 600, file) : nil
      r.each_line do |l|
        lines << [Process.clock_gettime(Process::CLOCK_MONOTONIC), l.chomp]
        next unless l.start_with?("WARMED")

        if phase == :warmup
          Process.kill("INT", s[0])
          Process.kill("KILL", pid)
          break
        end
        s ||= sampler(pid, window, file)
      end
      _, status = Process.wait2(pid)
      if s
        Process.wait(s[0])
        s[1].join
      end
      samples = { window: s && s[2], log: log, file: file,
                  status: status.success? }
    end
    File.write(File.join(dir, "#{tag}.stdout.jsonl"),
               lines.map { |t, l| JSON.generate([t, l]) }.join("\n") + "\n")
    [lines, samples]
  end

  def iterations(lines)
    lines.filter_map do |t, l|
      m = l.match(/\AITER (\d+) (\S+) \S+ (\d+) (\d+)/) or next
      { "i" => m[1].to_i, "at" => t, "ms" => m[2].to_f,
        "gc_ms" => m[3].to_i, "gc_count" => m[4].to_i }
    end
  end

  def median(values)
    s = values.sort
    return nil if s.empty?

    s.size.odd? ? s[s.size / 2] : (s[s.size / 2 - 1] + s[s.size / 2]) / 2.0
  end

  def window_stats(iters, from, to)
    inside = iters.select do |it|
      it["at"] - it["ms"] / 1000.0 >= from && it["at"] <= to
    end
    return {} if inside.size < 2

    ms = inside.sum { |it| it["ms"] }
    gc = inside.last["gc_ms"] - inside.first["gc_ms"]
    { "iterations" => inside.size,
      "median_ms" => median(inside.map { |it| it["ms"] }),
      "iter_ms_sum" => ms, "cruby_gc_ms" => gc,
      "cruby_gc_share" => ms.positive? ? gc / (ms - inside.first["ms"]) : nil }
  end

  # Foreign sends per steady iteration: two coverage runs, differenced.
  def sends(suite, bench, exe, dir, iters)
    counts = [0, iters].map do |n|
      text = ""
      suite.with_script(bench, probe: true) do |script, env, _warm|
        env = env.merge("RPYYARV_COVERAGE" => "1", "MIN_BENCH_ITRS" => n.to_s)
        out, err, = Open3.capture3(env, exe, script)
        text = (out + err).scrub
      end
      File.write(File.join(dir, "#{bench}-coverage-#{n}.txt"), text)
      { "sends" => text[/sends: rpyyarv (\d+), cruby (\d+)/].to_s,
        "by_name" => text.scan(/cruby send: (.*?) (\d+)$/)
                         .to_h { |k, v| [k, v.to_i] },
        "by_site" => text.scan(/cruby site: (.*?) (\d+)$/)
                         .to_h { |k, v| [k, v.to_i] } }
    end
    per = lambda do |key|
      counts[1][key].to_h do |k, v|
        [k, (v - counts[0][key].fetch(k, 0)).fdiv(iters)]
      end.sort_by { |_, v| -v }.to_h
    end
    native, foreign = [0, 1].map do |i|
      counts[1]["sends"].scan(/\d+/)[i].to_i -
        counts[0]["sends"].scan(/\d+/)[i].to_i
    end
    { "benchmark" => bench, "iterations" => iters,
      "native_per_iter" => native.fdiv(iters),
      "cruby_per_iter" => foreign.fdiv(iters),
      "by_name" => per.call("by_name"), "by_site" => per.call("by_site") }
  end

  # Samples pooled over processes, as percent of wall time per bucket.
  def report(path, phase)
    recs = File.readlines(path).map { |l| JSON.parse(l) }
    recs.group_by { |r| r["benchmark"] }.filter_map do |bench, rs|
      pool = Hash.new(0)
      rs = rs.select { |r| r[phase] && r[phase]["samples"].positive? }
      next if rs.empty?

      rs.each do |r|
        tag = "#{bench}-#{r["proc"]}"
        file = File.join(File.dirname(path), "#{tag}.#{phase}.sample.txt")
        log = File.join(File.dirname(path), "#{tag}.pypylog")
        r[phase] = summarize(file, "rpyyarv-jit", jit_ranges(log))
      end
      rs.each do |r|
        r[phase]["details"].each { |k, v| pool[k] += v }
      end
      total = pool.values.sum.to_f
      pct = pool.transform_values { |v| (100 * v / total).round(2) }
      buckets = BUCKETS.to_h do |b|
        [b, pct.select { |k, _| k.start_with?("#{b}/") }.values.sum.round(2)]
      end
      med = ->(key) { median(rs.filter_map { |r| r[key]["median_ms"] }) }
      { "benchmark" => bench, "samples" => total.to_i, "buckets" => buckets,
        "details" => pct.sort_by { |_, v| -v }.to_h,
        "sampled_median_ms" => med.call("sampled"),
        "after_median_ms" => med.call("after"),
        "gcstat_share" =>
          median(rs.filter_map { |r| r["sampled"]["cruby_gc_share"] }) }
    end
  end

  def main(argv)
    load_bench
    opts = { filters: [], procs: 1, window: 15, out: nil }
    OptionParser.new do |o|
      o.on("--filter NAME") { |v| opts[:filters] << v }
      o.on("--procs N", Integer) { |v| opts[:procs] = v }
      o.on("--window SECS", Integer) { |v| opts[:window] = v }
      o.on("--out DIR") { |v| opts[:out] = v }
      o.on("--summarize FILE") { |v| opts[:summarize] = v }
      o.on("--sends ITERS", Integer) { |v| opts[:sends] = v }
      o.on("--report JSONL") { |v| opts[:report] = v }
      o.on("--phase NAME") { |v| opts[:phase] = v }
      o.on("--exe PATH") { |v| opts[:exe] = File.expand_path(v) }
    end.parse!(argv)
    if opts[:report]
      puts JSON.pretty_generate(report(opts[:report], opts[:phase] || "steady"))
      return 0
    end
    if opts[:summarize]
      puts JSON.pretty_generate(summarize(opts[:summarize], "rpyyarv-jit"))
      return 0
    end
    abort "--out is required" unless opts[:out]

    dir = File.expand_path(opts[:out])
    FileUtils.mkdir_p(dir)
    suite = RubyBenchSuite.new({ gem_require: true })
    names = suite.benchmarks.select do |b|
      opts[:filters].empty? || opts[:filters].include?(b)
    end
    exe = opts[:exe] || File.join(ROOT, "rpyyarv-jit")
    if opts[:sends]
      names.each do |bench|
        rec = sends(suite, bench, exe, dir, opts[:sends])
        File.open(File.join(dir, "sends.jsonl"), "a") do |f|
          f.puts(JSON.generate(rec))
        end
      end
      return 0
    end
    phase = (opts[:phase] || "steady").to_sym
    out = File.join(dir, "breakdown.jsonl")
    names.each do |bench|
      opts[:procs].times do |p|
        tag = "#{bench}-#{p}"
        puts "breakdown: #{tag} #{phase}"
        lines, s = run_one(suite, exe, bench, dir, opts[:window], tag, phase)
        iters = iterations(lines)
        warmed = lines.map(&:last).grep(/\AWARMED/).first&.split&.last.to_i
        win = s[:window] || {}
        rec = { "benchmark" => bench, "proc" => p, "phase" => phase,
                "status" => s[:status], "warmed_at" => warmed, "window" => win,
                phase.to_s => summarize(s[:file], File.basename(exe),
                                        jit_ranges(s[:log])),
                "sampled" => window_stats(iters, win[:start] || 0,
                                          win[:stop] || Float::INFINITY),
                "after" => win[:stop] ? window_stats(iters, win[:stop],
                                                     Float::INFINITY) : {} }
        File.open(out, "a") { |f| f.puts(JSON.generate(rec)) }
      end
    end
    0
  end
end

exit Breakdown.main(ARGV) if $PROGRAM_NAME == __FILE__
