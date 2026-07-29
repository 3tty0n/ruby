# Cross-check rpyyarv's hand-written decisions against insns.def.
#
# Generation covers facts; this covers decisions. It catches the failure mode
# that matters in practice: a hand-written table drifting out of step with the
# pinned CRuby without anyone noticing.
#
#   ruby verify.rb        (exit 1 on any problem)

require 'pathname'

TOP = Pathname.new(__dir__).parent.expand_path
$LOAD_PATH.unshift((TOP + 'tool').to_s)
require 'ruby_vm/models/instructions'

MAP = TOP + 'rpyyarv' + 'yarv_map.py'
GENERATED = TOP + 'rpyyarv' + 'yarv_insns.py'

$problems = []
def problem(msg)
  $problems << msg
end

def bare
  @bare ||= RubyVM::Instructions.select { |i| i.class.name =~ /BareInstruction/ }
end

def unified
  @unified ||= RubyVM::Instructions.select { |i| i.class.name =~ /OperandsUnification/ }
end

# Pull the OPCODES keys and the operand-type sets out of yarv_map.py without
# executing it: it imports insns, which is RPython-side code.
def parse_map
  src = MAP.read
  section = ->(name) {
    body = src[/^#{name}\s*=\s*(?:frozenset\(\[)?(.*?)(?:\]\))?\n\}?\n/m, 1] ||
           src[/^#{name}\s*=\s*\{(.*?)^\}/m, 1] ||
           src[/^#{name}\s*=\s*frozenset\(\[(.*?)\]\)/m, 1]
    body ? body.scan(/'([^']+)'/).flatten : nil
  }
  {
    opcodes: section.('OPCODES'),
    supported: section.('SUPPORTED_OPERAND_TYPES'),
    discarded: section.('DISCARDED_OPERAND_TYPES'),
  }
end

map = parse_map
if map[:opcodes].nil? || map[:opcodes].empty?
  abort "verify: could not parse OPCODES out of #{MAP}"
end

known = bare.map(&:name)
specialized = unified.map(&:name)

# 1. every mapped name is a real base instruction
map[:opcodes].each do |name|
  next if known.include?(name)
  if specialized.include?(name)
    problem "#{name}: specialized variant in OPCODES; map the base instruction " \
            "and normalize via yarv_insns.SPECIALIZED"
  else
    problem "#{name}: not an instruction in insns.def (renamed or removed?)"
  end
end

# 2. every operand of a mapped instruction is either transformable or
#    explicitly discarded -- otherwise the loader mis-decodes it silently
supported = (map[:supported] || []) + (map[:discarded] || [])
map[:opcodes].each do |name|
  insn = bare.find { |i| i.name == name } or next
  insn.operands.each do |o|
    next if supported.include?(o[:type])
    problem "#{name}: operand type #{o[:type]} is neither supported nor " \
            "discarded in yarv_map.py"
  end
end

# 3. the generated file is in step with the current tree
if GENERATED.exist?
  gen = GENERATED.read
  if (n = gen[/^INSTRUCTION_COUNT = (\d+)/, 1]&.to_i) && n != bare.size
    problem "yarv_insns.py has INSTRUCTION_COUNT=#{n} but insns.def now has " \
            "#{bare.size}; regenerate"
  end
  ver = (TOP + 'include/ruby/version.h').read
  cur = %w[MAJOR MINOR TEENY]
        .map { |k| ver[/define RUBY_API_VERSION_#{k}\s+(\d+)/, 1] }.join('.')
  if (g = gen[/^RUBY_API_VERSION = '([^']+)'/, 1]) && g != cur
    problem "yarv_insns.py was generated for ruby #{g} but the tree is #{cur}; " \
            "regenerate"
  end
else
  problem "#{GENERATED.relative_path_from(TOP)} missing; run `make -C rpyvmgen`"
end

# Coverage is reported, not enforced -- a small map is expected early on.
covered = map[:opcodes].count { |n| known.include?(n) }
puts "mapped #{covered}/#{bare.size} instructions defined in insns.def"

if $problems.empty?
  puts 'verify: ok'
  exit 0
else
  $problems.each { |p| puts "NG: #{p}" }
  puts "verify: #{$problems.size} problem(s)"
  exit 1
end
