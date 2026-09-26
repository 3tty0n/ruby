# The host CRuby tree both scripts read, and its rpyyarv/host/<tag>/ entry.
require 'pathname'

HERE = Pathname.new(__dir__).parent.expand_path
TOP = Pathname.new(ENV['RPYYARV_HOST_SRC'] || HERE).expand_path
HOST_TAG = 'v' + %w[MAJOR MINOR].map { |k|
  (TOP + 'include/ruby/version.h').read[/define RUBY_API_VERSION_#{k}\s+(\d+)/, 1]
}.join('_')
HOST_DIR = HERE + 'rpyyarv/host' + HOST_TAG

# `rename HOST_NAME NAME` lines: the host renamed an instruction RPyYARV
# still calls NAME. Both names reach NAME_TO_OP; NAME alone gets a constant.
DESCRIPTION = HOST_DIR + 'description'
RENAMES = (DESCRIPTION.exist? ? DESCRIPTION.readlines : [])
          .map(&:split).select { |w| w[0] == 'rename' }
          .to_h { |_, from, to| [from, to] }

def canon(name) = RENAMES.fetch(name, name)
