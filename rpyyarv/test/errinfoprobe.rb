# CRuby's own C clears ec->errinfo (exc_equal, error.c:2194) where a CRuby
# rescue frame would hold `$!` in an svar; RPyYARV pushes no such frame.
def rechk(tag)
  begin; raise; rescue => e; puts "#{tag}: #{e.class}(#{e.message})"; end
end
begin
  raise "outer"
rescue
  e = RuntimeError.new("x")
  rechk(:start)
  e == nil
  rechk(:exc_eq_nil)
  [e].include?(nil)
  rechk(:include_nil)
  Integer("nope") rescue nil
  rechk(:bad_integer)
  class FreshClass; end
  rechk(:classdef)
  p $!.message
end
p $!

# ec->errinfo stays nil while a rescue body runs, so `cause` has to come
# from the rescue's own $! at the moment the new exception is raised.
begin
  begin
    raise "inner"
  rescue
    def reraise; raise; end
    begin; reraise; rescue => e; p [:bare, e.message]; end
    raise ArgumentError, "outer"
  end
rescue => e
  p [e.class, e.cause.class, e.cause.message]
end
