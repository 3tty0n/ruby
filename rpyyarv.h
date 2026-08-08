#ifndef RPYYARV_H
#define RPYYARV_H 1
//
// This file contains definitions rpyyarv exposes to the CRuby codebase
//

#include "ruby/internal/config.h"
#include "ruby/internal/dllexport.h"
#include "ruby/internal/value.h"

void rb_rpyyarv_constant_state_changed(ID id);

RBIMPL_SYMBOL_EXPORT_BEGIN()
// rpyyarv links against libruby from outside the tree, so unlike YJIT it cannot be compiled in and registers its callback at runtime instead.
void rb_rpyyarv_set_constant_hook(void (*fn)(ID id));
RBIMPL_SYMBOL_EXPORT_END()

#endif // #ifndef RPYYARV_H
