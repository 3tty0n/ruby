# A bmethod CRuby dispatches gets its keywords as a flagged trailing Hash.
class Fields
  [:string, :integer].each do |type|
    define_method(type) do |name, **options|
      [type, name, options]
    end
  end
end
f = Fields.new
p f.string(:a, default: "x")
p f.string(:a)
p f.integer(:b, default: 1, null: false)
p f.send(:string, :c, default: 2)
