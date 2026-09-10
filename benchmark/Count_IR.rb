# コマンドライン引数があるか確認
if ARGV.empty?
  puts "Usage: ruby count_insn.rb target.rb"
  exit 1
end

# コマンドライン引数の一つ目を取り出す
target = ARGV[0]

# RubyソースをISeqへコンパイル
iseq = RubyVM::InstructionSequence.compile_file(target)

# ディスアセンブル結果取得
disasm = iseq.disasm

# 出現回数表
counter = Hash.new(0)

disasm.each_line do |line|
  cols = line.split

  # 空行を除外
  next if cols.empty?

  # 先頭が命令アドレスでない行を除外
  next unless cols[0] =~ /^\d+$/
  
  insn = cols[1]
  counter[insn] += 1
end

puts "=== instruction count ==="

counter
  .sort_by { |_, count| -count }
  .each do |insn, count|
    printf "%-30s %d\n", insn, count
  end