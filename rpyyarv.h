#ifndef RPYYARV_H
#define RPYYARV_H 1
// Definitions rpyyarv exposes to the CRuby codebase.

#include "ruby/internal/config.h"
#include "ruby/internal/dllexport.h"
#include "ruby/internal/value.h"

void rb_rpyyarv_constant_state_changed(ID id);
void rb_rpyyarv_method_state_changed(void);

// A switch brackets coroutine_transfer, keyed by the rb_fiber_t address.
// unpark/born carry the arriving stack so the JIT depth window follows it.
typedef struct rb_rpyyarv_fiber_hooks {
    void (*park)(long key);
    void (*unpark)(long key, long stack_base, long stack_size);
    void (*born)(long key, long stack_base, long stack_size);
    void (*died)(long key);
} rb_rpyyarv_fiber_hooks_t;

RBIMPL_SYMBOL_EXPORT_BEGIN()
// rpyyarv links libruby from outside the tree, so it registers at runtime.
void rb_rpyyarv_set_constant_hook(void (*fn)(ID id));
void rb_rpyyarv_set_method_hook(void (*fn)(void));
void rb_rpyyarv_set_fiber_hooks(const rb_rpyyarv_fiber_hooks_t *hooks);
void rb_rpyyarv_fiber_kill_rethrow(void);
RBIMPL_SYMBOL_EXPORT_END()

#endif // #ifndef RPYYARV_H
