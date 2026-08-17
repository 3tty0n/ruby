# The native fast paths for Kernel#format/#sprintf and CGI.escapeHTML.
p format("%d", 3)
p format("%d %s %.2f %05x", 3, "hi", 1.5, 255)
p sprintf("%d", 42)
p format("%s", :sym)
p format("%-5s|", "ab")

begin
  format("%d")
rescue ArgumentError => e
  puts e.message
end
begin
  format("%d", "x")
rescue ArgumentError => e
  puts e.message
end
begin
  format("%z", 1)
rescue ArgumentError => e
  puts e.message
end

module MyFormat
  def format(*args)
    "patched:" + super
  end
end
class Object
  prepend MyFormat
end
p format("%d", 1)

require 'cgi/escape'
p CGI.escapeHTML("'&\"<>")
p CGI.escapeHTML("no special chars")
p CGI.escapeHTML("héllo wörld")
class SubStr < String
end
p CGI.escapeHTML(SubStr.new("<tag>"))
begin
  CGI.escapeHTML(42)
rescue TypeError => e
  puts e.class
end

class CGI
  class << self
    alias_method :orig_escapeHTML, :escapeHTML
    def escapeHTML(s)
      "patched:" + orig_escapeHTML(s)
    end
  end
end
p CGI.escapeHTML("<a>")
