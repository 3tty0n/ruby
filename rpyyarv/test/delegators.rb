# DelegateClass: bmethod frames must carry the method's own identity, so
# super inside define_method blocks resolves from the method, never from
# the frame the block was created in.

require 'delegate'

class Widget
  def label; 'widget-label'; end
  def double(n); n * 2; end
end

class WidgetD < DelegateClass(Widget); end

d = WidgetD.new(Widget.new)
puts d.label
puts d.double(21)
puts d.__getobj__.class
puts [d].map(&:label).first
puts d.method(:label).call

# The define_singleton_method blocks in DelegateClass call super(all).
puts WidgetD.instance_methods.include?(:label)
puts WidgetD.public_instance_methods.include?(:double)

# SimpleDelegator's method_missing must see the instance, not Delegator.
s = SimpleDelegator.new('hello')
puts s.upcase
puts s.length

# super from an explicit define_method block resolves above the owner.
class Base
  def greet; 'base'; end
end
class Derived < Base
  define_method(:greet) { 'derived+' + super() }
end
puts Derived.new.greet
