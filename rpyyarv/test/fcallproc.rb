# An fcall to a CRuby-side private method with a foreign proc as its block
# must stay private-allowed, like the blockless boundary send is.
require_relative "fcallproc_use"
class KH
  def call_hidden(pr)
    hidden(&pr)
  end
end
k = KH.new
p k.call_hidden(k.make_proc)
