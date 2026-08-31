class Base
  def tag
    "base"
  end
end

class Sub < Base
end

module Extra
  def tag
    "extra"
  end
end

o = Sub.new
r = []
200.times { r << (o.respond_to?(:tag) ? o.tag : "none") }
r << o.is_a?(Extra).to_s
Base.include(Extra)
200.times { r << (o.respond_to?(:tag) ? o.tag : "none") }
r << o.is_a?(Extra).to_s
Sub.prepend(Extra)
200.times { r << o.tag }
puts r.uniq.inspect
puts Sub.ancestors.first(4).inspect
