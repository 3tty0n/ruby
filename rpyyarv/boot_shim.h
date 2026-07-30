/*
 * Thin C layer over CRuby APIs that cannot be called through an FFI:
 * macros (RUBY_INIT_STACK, RARRAY_LEN, RB_TYPE_P), the variadic rb_funcall,
 * and anything that may longjmp past the caller's frame.
 *
 * Shared by boot.py (rffi) and test/test_boot_ctypes.py (ctypes).
 */
#ifndef RPYYARV_BOOT_SHIM_H
#define RPYYARV_BOOT_SHIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Boot CRuby and return the compiled ISeq of the main script, unexecuted.
 * Runs ruby_sysinit -> ruby_init_stack -> ruby_init -> ruby_options, but
 * never ruby_run_node, so CRuby does not execute the script.
 *
 * ruby_init_stack needs an address on the machine stack; passing a heap
 * address breaks the conservative GC scan range. Hence this wrapper.
 *
 * Returns NULL when ruby_options yields no ISeq (--version, syntax error);
 * *status_out then holds the exit status.
 */
void *rpyyarv_boot(int argc, char **argv, int *status_out);

int rpyyarv_cleanup(int status);

/* Zero-arg method call guarded by rb_protect. *state is non-zero on raise. */
uintptr_t rpyyarv_call0(uintptr_t recv, const char *mid, int *state);

/* rb_iseq_t is incomplete here, so the ISeq crosses the FFI as void *. */
uintptr_t rpyyarv_iseqw_new(void *iseq);

const char *rpyyarv_cstr(uintptr_t str);
const char *rpyyarv_inspect_cstr(uintptr_t obj);

long      rpyyarv_ary_len(uintptr_t ary);
uintptr_t rpyyarv_ary_entry(uintptr_t ary, long idx);

int rpyyarv_is_array(uintptr_t v);
int rpyyarv_is_symbol(uintptr_t v);
int rpyyarv_is_fixnum(uintptr_t v);
int rpyyarv_is_string(uintptr_t v);
int rpyyarv_is_hash(uintptr_t v);
int rpyyarv_is_nil(uintptr_t v);
int rpyyarv_is_true(uintptr_t v);
int rpyyarv_is_false(uintptr_t v);

long rpyyarv_num2long(uintptr_t v);

/* hash[:key], for the to_a side tables (misc, params, call data). */
uintptr_t rpyyarv_hash_aref(uintptr_t hash, const char *key);

/* Symbol#to_s without a rb_funcall round trip. */
const char *rpyyarv_sym_cstr(uintptr_t sym);

#ifdef __cplusplus
}
#endif

#endif /* RPYYARV_BOOT_SHIM_H */
