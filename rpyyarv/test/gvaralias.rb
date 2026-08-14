# `alias $new $old` compiles to core#set_variable_alias on the frozen core.
$orig = 42
alias $aliased $orig
p $aliased
$aliased = 7
p $orig

alias $ERR $!
begin
  raise 'boom'
rescue
  p $ERR.message
end
