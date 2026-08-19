def kw_taker(a:, b: 2)
  [a, b]
end
def fwd(h, &blk)
  kw_taker(**h, &blk)
end
p fwd({a: 1})
p fwd({a: 1, b: 3}) { :ignored }
class HashLike
  def to_hash
    { a: 9 }
  end
end
p fwd(HashLike.new)
def fwd_nil(h, &blk)
  kw_taker(a: 5, **h, &blk)
end
p fwd_nil(nil)
begin
  fwd({a: 1, c: 7})
rescue ArgumentError => e
  puts e.message
end
