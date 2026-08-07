# Required by trampoline_chain.rb. The class variable is more than RPyYARV's
# loader represents, so CRuby runs this file; every call it makes back into a
# class RPyYARV defined has to find the method anyway.
class PuntBase
  @@kind = "punt"

  def kind
    @@kind
  end

  def describe
    "#{kind}/#{label}"
  end
end

def punted_report(obj)
  "#{obj} #{obj.inspect} #{obj.plain(7)}"
end
