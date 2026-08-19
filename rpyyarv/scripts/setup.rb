#!/usr/bin/env ruby
# frozen_string_literal: true

HERE  = File.dirname(File.expand_path(__FILE__))
ROOT  = File.dirname(HERE)
TOP   = File.dirname(ROOT)
BUILD = ENV.fetch("RPYYARV_BUILD", File.join(TOP, "build"))
GEMS  = ENV.fetch("BENCH_GEMS", File.join(ROOT, ".bench-gems"))
RUBY  = File.join(BUILD, "ruby")
LIBVAR = RUBY_PLATFORM.include?("darwin") ? "DYLD_LIBRARY_PATH" : "LD_LIBRARY_PATH"

unless File.executable?(RUBY)
  warn "error: no #{RUBY} -- build CRuby first (./configure --enable-shared " \
       "&& make), or point RPYYARV_BUILD at an existing build"
  exit 1
end

# Same uninstalled load path bench-setup and bench.rb use for $(BUILD)/ruby.
def uninstalled_rubylib
  arch = Dir.glob(File.join(BUILD, ".ext", "*"))
             .find { |d| File.directory?(d) && File.basename(d) != "common" }
  [File.join(TOP, "lib"), File.join(BUILD, ".ext", "common"), BUILD, arch]
    .compact.join(File::PATH_SEPARATOR)
end

def bench_gems_env
  { "RUBYLIB" => uninstalled_rubylib, LIBVAR => BUILD,
    "RUBYOPT" => "-r#{File.join(HERE, "ruby-build-rbconfig")}",
    "GEM_HOME" => GEMS, "GEM_PATH" => GEMS, "BUNDLE_PATH" => GEMS,
    "BUNDLE_APP_CONFIG" => File.join(GEMS, ".bundle") }
end

puts "== installing ruby-bench gems (make bench-setup)"
system("make", "-C", ROOT, "bench-setup")
warn "warning: some gem installs failed, see #{GEMS}/log" unless $?.success?

rails_dir = File.join(ROOT, "ruby-bench", "benchmarks", "railsbench")
env = bench_gems_env
gems_ok = system(env, RUBY, File.join(TOP, "libexec", "bundle"), "check",
                  chdir: rails_dir, out: File::NULL, err: File::NULL)

if gems_ok
  puts "== railsbench: db:migrate db:seed"
  ok = system(env, RUBY, "bin/rails", "db:migrate", chdir: rails_dir) &&
       system(env, RUBY, "bin/rails", "db:seed", chdir: rails_dir)
  warn "warning: railsbench db:migrate/db:seed failed" unless ok
else
  warn "warning: railsbench gems not installed, skipping db:migrate/db:seed"
end

puts <<~SUMMARY

  setup done.
    build ruby:  #{RUBY}
    bench gems:  #{GEMS}

  For manual `make bench`/`make awfy` runs, export:
    RPYYARV_BUILD=#{BUILD}
    BENCH_GEMS=#{GEMS}
    GEM_PATH=<gem path for the driver ruby running scripts/bench.rb>
    AWFY_RUBYLIB=<path to the awfy suite's set/subclass_compatible.rb>
SUMMARY
