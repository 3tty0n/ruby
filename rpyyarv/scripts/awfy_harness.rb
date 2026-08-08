#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Drop-in replacement for AWFY's harness.rb + run.rb that rpyyarv runs natively.
#
# The original punts: run.rb's class-name fallback uses $1/$2, and getspecial is
# unimplemented, so rpyyarv sends the whole file -- and every benchmark it
# requires -- to CRuby. Stdout here is byte-identical to the original apart from
# the timing numbers.

class Run
  attr_accessor :name, :benchmark_suite, :num_iterations, :inner_iterations

  def initialize(name)
    @name             = name
    @benchmark_suite  = load_benchmark_suite(name)
    @total            = 0
    @num_iterations   = 1
    @inner_iterations = 1
  end

  # AWFY sits next to this script when it is copied into the suite, otherwise
  # it is the checkout one level up from scripts/.
  def self.benchmark_dir
    here = File.dirname(File.expand_path(__FILE__))
    from_env = ENV['AWFY_BENCH_DIR']
    return from_env if from_env && from_env != ''
    return here if File.exist?(here + '/benchmark.rb')

    File.dirname(here) + '/awfy/benchmarks/Ruby'
  end

  # run.rb spells this /([a-z])([A-Z])/ with $1/$2; backrefs are getspecial.
  def hyphenate(name)
    out = +''
    i = 0
    len = name.length
    while i < len
      c = name[i]
      out << c
      if i + 1 < len
        d = name[i + 1]
        out << '-' if c >= 'a' && c <= 'z' && d >= 'A' && d <= 'Z'
      end
      i += 1
    end
    out
  end

  def load_benchmark_suite(benchmark_name)
    dir = Run.benchmark_dir
    if File.exist?("#{dir}/#{benchmark_name.downcase}.rb")
      benchmark_file = benchmark_name.downcase
    else
      benchmark_file = hyphenate(benchmark_name).downcase
    end
    unless require("#{dir}/#{benchmark_file}.rb")
      raise "#{benchmark_file} was already loaded"
    end

    Object.const_get(benchmark_name)
  end

  def run_benchmark
    @total = 0
    puts "Starting #{@name} benchmark ..."
    do_runs(@benchmark_suite.new)
    report_benchmark
    puts ''
  end

  def measure(bench)
    start_time = Process.clock_gettime(Process::CLOCK_MONOTONIC, :nanosecond)
    unless bench.inner_benchmark_loop(@inner_iterations)
      raise 'Benchmark failed with incorrect result'
    end

    end_time = Process.clock_gettime(Process::CLOCK_MONOTONIC, :nanosecond)

    run_time = (end_time - start_time) / 1000
    print_result(run_time)
    @total += run_time
  end

  def do_runs(bench)
    @num_iterations.times { measure(bench) }
  end

  def report_benchmark
    puts "#{@name}: iterations=#{@num_iterations} average: #{@total / @num_iterations}us total: #{@total}us\n"
  end

  def print_result(run_time)
    puts "#{@name}: iterations=1 runtime: #{run_time}us"
  end

  def print_total
    puts "Total Runtime: #{@total}us"
  end
end

def process_arguments(args)
  run = Run.new(args[0])

  if args.size > 1
    run.num_iterations = Integer(args[1])
    run.inner_iterations = Integer(args[2]) if args.size > 2
  end
  run
end

def print_usage
  puts './harness.rb [benchmark] [num-iterations [inner-iter]]'
  puts ''
  puts '  benchmark      - benchmark class name '
  puts '  num-iterations - number of times to execute benchmark, default: 1'
  puts '  inner-iter     - number of times the benchmark is executed in an inner loop, '
  puts '                   which is measured in total, default: 1'
end

if ARGV.size < 1
  print_usage
  exit 1
end

run = process_arguments(ARGV)
run.run_benchmark
run.print_total
