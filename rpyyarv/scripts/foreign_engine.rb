# Engines that are not builds of this checkout's CRuby carry their own stdlib,
# C extensions, and gems.  The uninstalled-CRuby variables the harness exports
# must not reach them: RUBYLIB would make them dlopen build/.ext bundles linked
# against libruby, and the shared gem set holds extensions built for CRuby.
module ForeignEngine
  NAMES = %w[truffleruby truffleruby-native jruby].freeze
  CRUBY_KEYS = %w[DYLD_LIBRARY_PATH LD_LIBRARY_PATH RUBYLIB RUBYOPT
                  GEM_HOME GEM_PATH BUNDLE_PATH BUNDLE_APP_CONFIG].freeze

  def self.foreign?(name) = NAMES.include?(name)

  # nil unsets a variable the harness process itself inherited.
  def self.clean_env = CRUBY_KEYS.to_h { |k| [k, nil] }

  # The engine's own gem set, filled by scripts/bench-setup-foreign.
  def self.env(name, gems_root)
    gems = "#{gems_root}-#{name}"
    return clean_env unless File.directory?(gems)

    clean_env.merge("GEM_HOME" => gems, "GEM_PATH" => gems,
                    "BUNDLE_PATH" => gems,
                    "BUNDLE_APP_CONFIG" => File.join(gems, ".bundle"))
  end
end
