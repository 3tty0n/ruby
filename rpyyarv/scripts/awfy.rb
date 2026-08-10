#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Back-compat entry point for `make awfy`: the AWFY suite of scripts/bench.rb.

require "rbconfig"

exec(RbConfig.ruby, File.join(File.dirname(File.expand_path(__FILE__)), "bench.rb"),
     "--suite", "awfy", *ARGV)
