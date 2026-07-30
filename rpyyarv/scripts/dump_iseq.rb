#!/usr/bin/env ruby
#
# Dump a compiled ISeq in the text format rpyyarv/iseqdump.py parses.
#
#   ruby scripts/dump_iseq.rb SCRIPT.rb > SCRIPT.iseq
#
# A transliteration of RubyVM::InstructionSequence#to_a, not an
# interpretation of it: what RPyYARV supports is decided on the Python side.
# The boot path will build the same records straight from the to_a VALUEs.
#
# Records are tab-separated and only their last field may contain spaces.
# Nested ISeqs are flattened into a numbered table and referenced by index.
#
#   dump      <version> <ruby version> <source path>
#   iseq      <index> <type> <label>
#   locals    <count>
#   stackmax  <count>
#   params    <lead_num> <other param keys, comma separated>
#   catch     <catch table size>
#   insn      <name> <operand>...
#   label     <name>          -- sits in front of the next insn
#   event     <name>          -- RUBY_EVENT_*
#   line      <number>
#   endiseq
#
# Operand tokens, one per to_a operand:
#
#   i:<int>   Integer          n:  nil        t:  true       f:  false
#   y:<name>  Symbol: an ID, a Symbol literal, or a label reference
#   s:<text>  String
#   q:<index> nested ISeq
#   a:<item>,<item>...  Array; each item is a token whose backslashes and
#             commas are escaped again, so nesting stays unambiguous
#   c:<argc>,<flags>,<kwarg?>,<mid>   CALL_DATA
#   x:<text>  anything else, verbatim, so a refusal can name it
#
# In y:/s:/x: text, backslash, tab, newline and return are backslash-escaped.

FORMAT_VERSION = 1
ISEQ_MAGIC = 'YARVInstructionSequence/SimpleDataFormat'

# Must match rpyyarv/to_a_layout.py, which bootiseq.py enforces at run time.
TO_A_LENGTH = 14
TO_A_LAYOUT = [[0, String], [1, Integer], [2, Integer], [4, Hash],
               [5, String], [8, Integer], [9, Symbol], [10, Array],
               [11, Hash], [12, Array], [13, Array]].freeze
MOVED = 'iseq_data_to_ary in iseq.c moved a field; update to_a_layout.py'

def check_layout!(ary)
  if ary.size != TO_A_LENGTH
    abort "to_a has #{ary.size} elements, expected #{TO_A_LENGTH}: #{MOVED}"
  end
  TO_A_LAYOUT.each do |index, klass|
    next if ary[index].is_a?(klass)
    abort "to_a[#{index}] holds #{ary[index].class}, expected #{klass}: #{MOVED}"
  end
  return if ary[0] == ISEQ_MAGIC
  abort "to_a[0] is #{ary[0].inspect}, expected #{ISEQ_MAGIC.inspect}: #{MOVED}"
end

def esc(str)
  out = ''
  str.each_char do |c|
    case c
    when "\\" then out << '\\\\'
    when "\t" then out << '\\t'
    when "\n" then out << '\\n'
    when "\r" then out << '\\r'
    else out << c
    end
  end
  out
end

def esc_item(tok)
  out = ''
  tok.each_char do |c|
    case c
    when "\\" then out << '\\\\'
    when ','   then out << '\\c'
    else out << c
    end
  end
  out
end

def iseq_array?(obj)
  obj.is_a?(Array) && obj[0] == ISEQ_MAGIC
end

class Dumper
  def initialize(io)
    @io = io
    @queue = []
  end

  def dump(root, path)
    row('dump', FORMAT_VERSION, RUBY_VERSION, path)
    intern(root)
    i = 0
    while i < @queue.size
      emit(i, @queue[i])
      i += 1
    end
  end

  private

  def row(*fields)
    @io.puts(fields.join("\t"))
  end

  # Each nested ISeq appears exactly once in to_a.
  def intern(ary)
    @queue << ary
    @queue.size - 1
  end

  def emit(index, ary)
    check_layout!(ary)
    _magic, _major, _minor, _format, misc, label, _path, _abs, _lineno,
      type, locals, params, catch_table, body = ary

    row('iseq', index, type, label)
    row('locals', locals.size)
    row('stackmax', misc[:stack_max])
    row('params', params.fetch(:lead_num, 0),
        (params.keys - [:lead_num]).join(','))
    row('catch', catch_table.size)

    body.each do |e|
      case e
      when Integer
        row('line', e)
      when Symbol
        row(e.to_s.start_with?('RUBY_EVENT_') ? 'event' : 'label', e.to_s)
      when Array
        row('insn', e[0].to_s, *e[1..-1].map { |o| operand(o) })
      else
        row('insn', '?', "x:#{esc(e.inspect)}")
      end
    end
    row('endiseq')
  end

  def operand(obj)
    case obj
    when Integer then "i:#{obj}"
    when nil     then 'n:'
    when true    then 't:'
    when false   then 'f:'
    when Symbol  then "y:#{esc(obj.to_s)}"
    when String  then "s:#{esc(obj)}"
    when Array
      if iseq_array?(obj)
        "q:#{intern(obj)}"
      else
        "a:" + obj.map { |o| esc_item(operand(o)) }.join(',')
      end
    when Hash
      if obj.key?(:mid) && obj.key?(:orig_argc)
        "c:#{obj[:orig_argc]},#{obj[:flag]},#{obj[:kw_arg] ? 1 : 0}," \
          "#{esc(obj[:mid].to_s)}"
      else
        "x:#{esc(obj.inspect)}"
      end
    else
      "x:#{esc(obj.inspect)}"
    end
  end
end

if $0 == __FILE__
  abort "usage: #{$0} SCRIPT.rb" if ARGV.empty?
  path = ARGV[0]
  Dumper.new($stdout).dump(
    RubyVM::InstructionSequence.compile_file(path).to_a, path)
end
