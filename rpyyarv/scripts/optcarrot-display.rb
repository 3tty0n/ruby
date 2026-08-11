#!/usr/bin/env ruby
# frozen_string_literal: true

optcarrot = ENV.fetch("OPTCARROT_DIR")
fps_limit = 60
args = []
i = 0
while i < ARGV.length
  arg = ARGV[i]
  if arg.start_with?("--fps-limit=")
    fps_limit = arg.split("=", 2)[1].to_i
  elsif arg == "--fps-limit"
    i += 1
    abort "--fps-limit requires a value" if i >= ARGV.length
    fps_limit = ARGV[i].to_i
  else
    args << arg
  end
  i += 1
end
abort "--fps-limit must be zero or greater" if fps_limit < 0
ARGV.replace(args)

require File.join(optcarrot, "lib", "optcarrot")
require File.join(optcarrot, "lib", "optcarrot", "driver", "sdl2_video")
Optcarrot.const_set(:DISPLAY_FPS_LIMIT, fps_limit)
require_relative "optcarrot-display-driver"

Optcarrot::NES.new.run
