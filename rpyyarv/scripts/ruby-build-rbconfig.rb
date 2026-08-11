# Make native gem extensions use this uninstalled Ruby build.
require 'rbconfig'

root = File.expand_path('../..', __dir__)
build = File.join(root, 'build')
arch = RbConfig::CONFIG.fetch('arch')

overrides = {
  'prefix' => build,
  'bindir' => build,
  'libdir' => build,
  'rubyhdrdir' => File.join(root, 'include'),
  'rubyarchhdrdir' => File.join(build, '.ext', 'include', arch),
  'archhdrdir' => File.join(build, '.ext', 'include', arch),
}

overrides.each do |key, value|
  RbConfig::CONFIG[key] = value
  RbConfig::MAKEFILE_CONFIG[key] = value
end
