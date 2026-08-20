#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Back-compat entry point for `make awfy`: the AWFY suite of scripts/bench.rb.

build = ENV.fetch("RPYYARV_BUILD", File.expand_path("../../build", __dir__))
exec(File.join(build, "ruby"), File.join(__dir__, "bench.rb"),
     "--suite", "awfy", *ARGV)
