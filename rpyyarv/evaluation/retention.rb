#!/usr/bin/env ruby
# frozen_string_literal: true

# Which host objects stay alive only because RPyYARV roots them.  Reads a
# heap dump taken after a full GC (footprint.rb --dump) and splits the
# roots into CRuby's own and RPyYARV's: the mark hook's walk, segmented by
# the coverage report's root inventory, and the VM's global-object list,
# which rb_gc_register_mark_object fills for both runtimes.  An object is
# retained by a root set when no CRuby root reaches it; exclusive when only
# that set does.
#
#   ruby evaluation/retention.rb HEAP.json [COVERAGE_OUTPUT] [--json]

require "json"

module Retention
  module_function

  def load(path)
    nodes = {}
    roots = Hash.new { |h, k| h[k] = [] }
    File.foreach(path) do |l|
      o = JSON.parse(l)
      if o["type"] == "ROOT"
        roots["root:#{o['root']}"].concat(o["references"] || [])
        next
      end
      nodes[o["address"]] = o
    end
    [nodes, roots]
  end

  # The inventory's order is the hook's (gcroots._mark_all): pinned,
  # classes, held, forever; the remainder (errinfo, pools, bmethods, const
  # cache, frames) is one set, as its immediates are skipped uncounted.
  def hook_sets(nodes, hook, inv)
    refs = hook ? hook["references"] || [] : []
    pinned = inv[:pinned].to_i
    classes = refs[pinned, inv[:classes].to_i] || []
    kept = inv[:held].to_i + inv[:forever].to_i
    single, other = classes.partition { nodes[_1]&.dig("singleton") }
    { "hook:pinned" => refs.first(pinned),
      "hook:classes/singleton" => single, "hook:classes/other" => other,
      "hook:held+forever" => refs[pinned + classes.size, kept] || [],
      "hook:pools+caches+frames" => refs.drop(pinned + classes.size + kept) }
  end

  def pin_sets(nodes, lists)
    entries = lists.flat_map { nodes[_1]["references"] || [] }
                   .reject { lists.include?(_1) }
    entries.group_by do |a|
      o = nodes[a] || {}
      case o["type"]
      when "IMEMO" then o["imemo_type"] == "iseq" ? "pin:iseq" : "pin:other"
      when "DATA"
        o["struct"] == "T_IMEMO/iseq" ? "pin:iseq" : "pin:other"
      when "STRING" then "pin:string"
      when "CLASS", "MODULE" then "pin:class"
      else "pin:other"
      end
    end
  end

  def walk(nodes, starts, blocked, seen)
    stack = starts.dup
    until stack.empty?
      a = stack.pop
      next if seen.key?(a) || blocked.key?(a) || !nodes.key?(a)

      seen[a] = true
      stack.concat(nodes[a]["references"] || [])
    end
    seen
  end

  # An ISeq wrapper reports its ISeq's size: count the wrapper's slot only.
  def size(o)
    o["struct"] == "T_IMEMO/iseq" ? o["slot_size"].to_i : o["memsize"].to_i
  end

  def bytes(nodes, addrs) = addrs.sum { size(nodes[_1]) }

  def kind(o)
    o["type"] == "IMEMO" ? "IMEMO/#{o['imemo_type']}" : o["type"]
  end

  def histogram(nodes, addrs)
    addrs.group_by { kind(nodes[_1]) }
         .transform_values { |v| [v.size, bytes(nodes, v)] }
         .sort_by { -_2[1] }.to_h
  end

  # Every root set, CRuby's by dump category and RPyYARV's, walked on its
  # own; an object's owners are the sets that reach it.
  def analyse(path, inv)
    nodes, roots = load(path)
    hook = nodes.values.find { _1["struct"] == "rpyyarv/gc_mark_hook" }
    lists = nodes.keys.select { nodes[_1]["struct"] == "VM/pin_array_list" }
    blocked = lists.to_h { [_1, true] }
    blocked[hook["address"]] = true if hook
    # A CRuby frame running an RPyYARV block: its ifunc names a handle.
    ifuncs = nodes.values.select { _1["struct"] == "VM/thread" }
                  .flat_map { _1["references"] || [] }
                  .select { nodes[_1]&.dig("imemo_type") == "ifunc" }.uniq
    ifuncs.each { blocked[_1] = true }
    rpy = hook_sets(nodes, hook, inv).merge(pin_sets(nodes, lists))
    rpy["thread:ifunc"] = ifuncs.flat_map { nodes[_1]["references"] || [] }
    sets = roots.merge(rpy)
    owner = Hash.new { |h, k| h[k] = [] }
    sets.each do |name, starts|
      walk(nodes, starts, blocked, {}).each_key { owner[_1] << name }
    end
    live = nodes.keys - lists - [hook&.dig("address")]
    only = owner.select { |_, v| v.all? { rpy.key?(_1) } }.keys
    out = { "live" => live.size, "live_bytes" => bytes(nodes, live),
            "host_malloc" => live.sum do
              size(nodes[_1]) - nodes[_1]["slot_size"].to_i
            end,
            "unreached" => (live - owner.keys).size,
            "rpyyarv_only" => only.size,
            "rpyyarv_only_bytes" => bytes(nodes, only),
            "types" => histogram(nodes, live), "sets" => {} }
    sets.each do |name, starts|
      mine = owner.select { |_, v| v.include?(name) }.keys
      excl = mine.select { owner[_1].size == 1 }
      kept = rpy.key?(name) ? mine & only : excl
      out["sets"][name] = { "roots" => starts.uniq.size,
                            "reached" => mine.size,
                            "retained" => kept.size,
                            "retained_bytes" => bytes(nodes, kept),
                            "exclusive" => excl.size,
                            "exclusive_bytes" => bytes(nodes, excl),
                            "exclusive_types" =>
                              histogram(nodes, excl).first(6).to_h }
    end
    out
  end

  INVENTORY = Regexp.new(
    'gc roots: classes (\d+), const pools (\d+) \((\d+) values\), ' \
    'pinned (\d+), held (\d+), forever (\d+)')

  def inventory(text)
    m = INVENTORY.match(text.to_s)
    return {} unless m

    { classes: m[1], pools: m[2], pool_values: m[3], pinned: m[4],
      held: m[5], forever: m[6] }
  end
end

if $PROGRAM_NAME == __FILE__
  json = ARGV.delete("--json")
  heap, cov = ARGV
  inv = Retention.inventory(cov && File.read(cov).scrub)
  r = Retention.analyse(heap, inv).merge("inventory" => inv)
  if json
    puts JSON.generate(r)
  else
    mb = ->(b) { format("%.2f MB", b / 1_048_576.0) }
    puts "live #{r['live']} (#{mb[r['live_bytes']]}), host malloc " \
         "#{mb[r['host_malloc']]}; rpyyarv-only #{r['rpyyarv_only']} " \
         "(#{mb[r['rpyyarv_only_bytes']]}); unreached #{r['unreached']}"
    r["sets"].each do |name, s|
      puts format("  %-26s roots %7d  retained %8d %10s  exclusive %8d %10s",
                  name, s["roots"], s["retained"], mb[s["retained_bytes"]],
                  s["exclusive"], mb[s["exclusive_bytes"]])
      puts "      #{s['exclusive_types']}" unless s["exclusive_types"].empty?
    end
  end
end
