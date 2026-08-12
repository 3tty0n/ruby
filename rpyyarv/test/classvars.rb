class A
  @@n = 0
  def self.bump = @@n += 1
  def bump2 = @@n += 2
  def self.n = @@n
  def n = @@n
end
A.bump
A.new.bump2
p A.n
p A.new.n
p A.class_variable_get(:@@n)

class B < A
  def self.peek = @@n
end
p B.peek
B.bump
p A.n

class C
  @@c = "c"
  class << self
    def viaself = @@c
  end
  def self.set(v) = @@c = v
end
p C.viaself
C.set("z")
p C.viaself

module M
  @@m = 1
  def self.get = @@m
end
p M.get

class D
  def self.missing = @@nope
end
begin
  D.missing
rescue NameError => e
  p :NameError
end

