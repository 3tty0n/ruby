Warning[:experimental] = false

module M
  BLOCK = proc { |x| x + 1 }
  TABLE = Ractor.make_shareable({ k: [1, +"s"], f: BLOCK })
end

p Ractor.make_shareable(M::BLOCK).equal?(M::BLOCK)
p M::BLOCK.frozen?
p Ractor.shareable?(M::BLOCK)
p M::BLOCK.call(1)

p M::TABLE.frozen?
p M::TABLE[:k].frozen?
p M::TABLE[:k][1].frozen?
p Ractor.shareable?(M::TABLE)
p M::TABLE[:f].call(41)
