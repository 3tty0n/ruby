# defined?($x) is DEFINED_GVAR; only rb_gvar_defined answers it exactly.
$set = 1
p defined?($set)
p defined?($never_set_at_all)
p defined?($stdout)
$maybe = nil
p defined?($maybe)
p defined?($0)
