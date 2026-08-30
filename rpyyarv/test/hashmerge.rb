# Hash#merge! converts a non-Hash argument with to_hash, like rb_to_hash_type.
class Convertible
  def to_hash
    { a: 1 }
  end
end

h = { b: 2 }
h.merge!(Convertible.new)
p h
p({ b: 2 }.update(Convertible.new))
p({ b: 2 }.merge!({ c: 3 }, { d: 4 }))
p({ a: 1 }.merge!(Convertible.new) { |_k, old, new| old + new })

[42, nil, "x"].each do |bad|
  begin
    {}.merge!(bad)
  rescue TypeError => e
    puts e.message
  end
end
