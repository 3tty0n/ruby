#ifndef RPYYARV_H
#define RPYYARV_H 1
// Definitions rpyyarv exposes to the CRuby codebase.

#include "ruby/internal/config.h"
#include "ruby/internal/dllexport.h"
#include "ruby/internal/value.h"
#include "ruby/internal/iterator.h"

void rb_rpyyarv_constant_state_changed(ID id);
void rb_rpyyarv_method_state_changed(VALUE klass, ID mid);

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
void rb_rpyyarv_set_method_hook(void (*fn)(VALUE, VALUE));
void rb_rpyyarv_set_fiber_hooks(const rb_rpyyarv_fiber_hooks_t *hooks);
void rb_rpyyarv_fiber_kill_rethrow(void);
VALUE rb_rpyyarv_frame_owner(void);
const void *rb_rpyyarv_frame_method_def(void);
int rb_rpyyarv_frame_bmethod(VALUE *owner_out, ID *mid_out, VALUE *proc_out);
const void *rb_rpyyarv_method_def(VALUE klass, ID mid);
VALUE rb_rpyyarv_proc_new(rb_block_call_func_t func, VALUE data, VALUE self_v);
VALUE rb_rpyyarv_ifunc_data(VALUE procval, rb_block_call_func_t func);
VALUE rb_rpyyarv_block_call_kw(VALUE obj, ID mid, int argc, const VALUE *argv,
                               rb_block_call_func_t bl_proc, VALUE data2,
                               int kw_splat, VALUE block_self);
VALUE rb_rpyyarv_call_with_proc_kw(VALUE obj, ID mid, int argc,
                                   const VALUE *argv, VALUE proc,
                                   int kw_splat);
RBIMPL_SYMBOL_EXPORT_END()

#endif // #ifndef RPYYARV_H
