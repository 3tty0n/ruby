#ifndef RPYYARV_H
#define RPYYARV_H 1
//
// This file contains definitions rpyyarv exposes to the CRuby codebase
//

#include "ruby/internal/config.h"
#include "ruby/internal/dllexport.h"
#include "ruby/internal/value.h"

void rb_rpyyarv_constant_state_changed(ID id);
void rb_rpyyarv_method_state_changed(void);

// Every fiber switch brackets coroutine_transfer with park/unpark, keyed by the rb_fiber_t address; born fires on a new fiber's first instruction and died from fiber_free.
typedef struct rb_rpyyarv_fiber_hooks {
    void (*park)(long key);
    void (*unpark)(long key);
    void (*born)(long key);
    void (*died)(long key);
} rb_rpyyarv_fiber_hooks_t;

RBIMPL_SYMBOL_EXPORT_BEGIN()
// rpyyarv links against libruby from outside the tree, so unlike YJIT it cannot be compiled in and registers its callback at runtime instead.
void rb_rpyyarv_set_constant_hook(void (*fn)(ID id));
void rb_rpyyarv_set_method_hook(void (*fn)(void));
void rb_rpyyarv_set_fiber_hooks(const rb_rpyyarv_fiber_hooks_t *hooks);
void rb_rpyyarv_fiber_kill_rethrow(void);
RBIMPL_SYMBOL_EXPORT_END()

#endif // #ifndef RPYYARV_H
