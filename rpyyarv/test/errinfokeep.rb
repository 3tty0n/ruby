# A method_missing send makes RPyYARV probe CRuby, which raises internally.
# That probe must not clear the $! the enclosing rescue is holding.
class Ghost
  def method_missing(name, *args)
    name
  end

  def respond_to_missing?(name, priv = false)
    true
  end
end

begin
  begin
    raise ArgumentError, "inner"
  rescue ArgumentError
    Ghost.new.anything
    puts $!.class
    raise
  end
rescue Exception => e
  puts "#{e.class}: #{e.message}"
end

def reraise
  yield
rescue StandardError
  Ghost.new.other
  raise
end

begin
  reraise { raise KeyError, "deep" }
rescue Exception => e
  puts "#{e.class}: #{e.message}"
end
