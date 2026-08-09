# Modules for test/mixins.rb. Required, so CRuby owns them and the registry
# only ever sees the classes that include them.
module MixWho
  def who; "MixWho"; end
end

module MixPre
  def who; "MixPre"; end
end

module MixLate
end

module MixLateBody
  def who; "MixLate"; end
end

module MixSuper
  def who; "MixSuper+" + super; end
end

module MixPreSuper
  def who; "MixPreSuper+" + super; end
end
