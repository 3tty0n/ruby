# Cross-check rpyyarv's hand-written decisions against insns.def.
#
#   ruby verify.rb        (exit 1 on any problem)

require 'pathname'

TOP = Pathname.new(__dir__).parent.expand_path
$LOAD_PATH.unshift((TOP + 'tool').to_s)
require 'ruby_vm/models/instructions'

MAP = TOP + 'rpyyarv' + 'yarv_map.py'
GENERATED = TOP + 'rpyyarv' + 'insns.py'

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

# Parse yarv_map.py textually rather than executing it: it is RPython-side
# code and importing it would need a Python interpreter on PATH.
def parse_map
  src = MAP.read
  emit = {}
  body = src[/^EMIT\s*=\s*\{(.*?)^\}/m, 1] or return nil
  body.scan(/'([^']+)':\s*\[([^\]]*)\]/) do |name, positions|
    emit[name] = positions.scan(/-?\d+/).map(&:to_i)
  end
  set = ->(name) {
    b = src[/^#{name}\s*=\s*frozenset\(\[(.*?)\]\)/m, 1]
    b ? b.scan(/'([^']+)'/).flatten : []
  }
  {
    emit: emit,
    supported: set.('SUPPORTED_OPERAND_TYPES'),
    discarded: set.('DISCARDED_OPERAND_TYPES'),
  }
end

map = parse_map
if map.nil? || map[:emit].empty?
  abort "verify: could not parse EMIT out of #{MAP}"
end

known = bare.map(&:name)
specialized = unified.map(&:name)
transformable = map[:supported] + map[:discarded]

map[:emit].each do |name, positions|
  # every implemented name is a real base instruction
  unless known.include?(name)
    if specialized.include?(name)
      problem "#{name}: specialized variant in EMIT; implement the base " \
              "instruction and normalize via insns.SPEC_BASE"
    else
      problem "#{name}: not an instruction in insns.def (renamed or removed?)"
    end
    next
  end

  insn = bare.find { |i| i.name == name }

  # every operand is either transformable or explicitly discarded
  insn.operands.each do |o|
    next if transformable.include?(o[:type])
    problem "#{name}: operand type #{o[:type]} is neither supported nor " \
            "discarded in yarv_map.py"
  end

  # emitted positions actually exist, and none is emitted twice
  positions.each do |p|
    next if p >= 0 && p < insn.operands.size
    problem "#{name}: EMIT position #{p} is out of range; the instruction " \
            "has #{insn.operands.size} operand(s)"
  end
  if positions.uniq.size != positions.size
    problem "#{name}: EMIT repeats an operand position"
  end
end

# the generated file is in step with the current tree
if GENERATED.exist?
  gen = GENERATED.read
  if (n = gen[/^INSTRUCTION_COUNT = (\d+)/, 1]&.to_i) && n != bare.size
    problem "insns.py has INSTRUCTION_COUNT=#{n} but insns.def now has " \
            "#{bare.size}; regenerate"
  end
  ver = (TOP + 'include/ruby/version.h').read
  cur = %w[MAJOR MINOR TEENY]
        .map { |k| ver[/define RUBY_API_VERSION_#{k}\s+(\d+)/, 1] }.join('.')
  if (g = gen[/^RUBY_API_VERSION = '([^']+)'/, 1]) && g != cur
    problem "insns.py was generated for ruby #{g} but the tree is #{cur}; " \
            "regenerate"
  end
else
  problem "#{GENERATED.relative_path_from(TOP)} missing; run `make -C rpyvmgen`"
end

# Coverage is reported, not enforced
covered = map[:emit].keys.count { |n| known.include?(n) }
puts "implemented #{covered}/#{bare.size} instructions defined in insns.def"

if $problems.empty?
  puts 'verify: ok'
  exit 0
else
  $problems.each { |p| puts "NG: #{p}" }
  puts "verify: #{$problems.size} problem(s)"
  exit 1
end
