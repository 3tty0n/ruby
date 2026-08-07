# Every exception path RPyYARV implements, checked against CRuby by diff.

def simple
  begin
    puts "body"
  rescue
    puts "not reached"
  else
    puts "else"
  ensure
    puts "ensure"
  end
end

def rescued
  begin
    raise ArgumentError, "bad"
    puts "not reached"
  rescue ArgumentError => e
    puts "rescued #{e.message}"
  else
    puts "not reached"
  ensure
    puts "ensure ran"
  end
end

def matching(x)
  begin
    raise x
  rescue TypeError
    "TypeError"
  rescue ArgumentError
    "ArgumentError"
  rescue StandardError => e
    "StandardError #{e.class}"
  end
end

def nested
  begin
    begin
      raise "inner"
    rescue RuntimeError => e
      puts "inner rescue #{e.message}"
      raise ArgumentError, "outer"
    end
  rescue ArgumentError => e
    puts "outer rescue #{e.message}"
  end
end

def builtin
  begin
    1 / 0
  rescue ZeroDivisionError => e
    "builtin #{e.message}"
  end
end

def deep(n)
  raise "from depth #{n}" if n == 0
  deep(n - 1)
end

def spanning
  begin
    deep(4)
  rescue RuntimeError => e
    puts "spanning #{e.message}"
  end
end

def ensure_on_break
  r = 0
  begin
    3.times do |i|
      r = i
      break
    end
  ensure
    puts "ensure after break r=#{r}"
  end
  r
end

def reraised
  begin
    begin
      raise "original"
    rescue
      raise
    end
  rescue => e
    puts "reraised #{e.message}"
  end
end

def unmatched
  begin
    begin
      raise TypeError, "wrong type"
    rescue ArgumentError
      puts "not reached"
    ensure
      puts "ensure before propagating"
    end
  rescue TypeError => e
    puts "caught later #{e.message}"
  end
end

def loop_rescue(n)
  total = 0
  i = 0
  while i < n
    begin
      raise "x" if i % 3 == 0
      total = total + 1
    rescue RuntimeError
      total = total + 10
    end
    i = i + 1
  end
  total
end

simple
rescued
puts matching(TypeError.new("t"))
puts matching(ArgumentError.new("a"))
puts matching(RuntimeError.new("r"))
nested
puts builtin
spanning
puts ensure_on_break
reraised
unmatched
puts loop_rescue(20)
puts "done"
