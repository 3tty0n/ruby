# $! of a running rescue survives a rescue that completes inside it.
def swallow; begin; raise "inner"; rescue; :ok; end; end
begin
  raise "outer"
rescue
  p $!.message
  swallow
  p $!.message
  begin; raise "again"; rescue; end
  p $!.message
  begin
    raise
  rescue RuntimeError => e
    p e.message
  end
end
p $!
