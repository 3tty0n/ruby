# A self-alias copies an inherited method down, then define_method through a
# &block forward replaces it in CRuby alone; the stale entry must not answer.
class Module
  def redefine(name, &block)
    alias_method name, name if method_defined?(name)
    define_method(name, &block)
  end
end

module ClassMethods
  def _routes
  end
end

class Base
  extend ClassMethods
end

class App < Base
end

routes = "ROUTES"
App.singleton_class.redefine(:_routes) { routes }
p App._routes
p App.singleton_class.instance_method(:_routes).bind(App).call
p App.method(:_routes).owner == App.singleton_class

# The same through a block with non-simple parameters.
App.singleton_class.redefine(:_routes) { |a = 1, *rest| [routes, a, rest] }
p App._routes
p App._routes(2, 3)

# An attr_reader alias must survive, and still read the ivar.
class Holder
  attr_reader :v
  alias_method :w, :v
  def initialize = @v = 7
end
p Holder.new.w

# An instance method: alias, then define_method through &block.
class Base
  def name_of
    "base"
  end
end
tag = "block"
Base.redefine(:name_of) { tag }
p Base.new.name_of
