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

/* rb_intern, so a caller can hoist the ID out of its send path. */
uintptr_t rpyyarv_intern(const char *name);

/* The Symbol for a name, for a :sym literal in a constant pool. */
uintptr_t rpyyarv_sym_new(const char *name);

/* Largest argc rpyyarv_funcallv* copies onto the machine stack. */
#define RPYYARV_MAX_ARGC 32

/*
 * rb_funcallv guarded by rb_protect; *state is non-zero on raise, -1 when
 * argc exceeds RPYYARV_MAX_ARGC. argv may live in memory CRuby never scans,
 * so it is copied to the machine stack before the call.
 */
uintptr_t rpyyarv_funcallv_id(uintptr_t recv, uintptr_t mid, int argc,
                              const uintptr_t *argv, int *state);
uintptr_t rpyyarv_funcallv(uintptr_t recv, const char *mid, int argc,
                           const uintptr_t *argv, int *state);

/* The toplevel `main`, pinned on first use. */
uintptr_t rpyyarv_top_self(void);

/* Bignum-safe long -> Integer, for fixnum overflow. */
uintptr_t rpyyarv_int2inum(long n);

/*
 * Immediate tags are compiled into the interpreter; this reports the ones
 * this libruby actually uses so a mismatch fails at startup instead of
 * silently mis-decoding every VALUE.
 */
void rpyyarv_special_consts(uintptr_t *qfalse, uintptr_t *qnil,
                            uintptr_t *qtrue, uintptr_t *fixnum_flag);

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

/*
 * VALUEs escaped into a foreign heap (ctypes lists here, RPython objects
 * later) are invisible to CRuby's conservative stack scan. The hook is a
 * TypedData object registered as a GC root whose dmark calls fn; fn marks
 * the escaped VALUEs with rpyyarv_gc_mark_value. NULL disables the hook.
 */
void rpyyarv_gc_set_mark_hook(void (*fn)(void));

/* rb_gc_mark on a VALUE; only meaningful while the mark hook is running. */
void rpyyarv_gc_mark_value(uintptr_t v);

void rpyyarv_gc_start(void);

uintptr_t rpyyarv_str_new(const char *s);

/* Both copy their input onto the machine stack first, as funcallv does. */
uintptr_t rpyyarv_ary_new(int n, const uintptr_t *elems);
uintptr_t rpyyarv_str_concat(int n, const uintptr_t *parts);

/*
 * The classes of the immediates, fetched once at boot so class_of() can
 * answer for a Fixnum without any rb_* call. Slot order is value.py's
 * C_* constants; RPYYARV_NCLASS is the length rpyyarv_core_classes fills.
 */
#define RPYYARV_NCLASS 12
void rpyyarv_core_classes(uintptr_t *out);

/* Class and object operations, each guarded by rb_protect. */
uintptr_t rpyyarv_define_class(uintptr_t cbase, uintptr_t id, uintptr_t super,
                               int *state);
uintptr_t rpyyarv_class_superclass(uintptr_t klass, int *state);
uintptr_t rpyyarv_obj_alloc(uintptr_t klass, int *state);
uintptr_t rpyyarv_const_get(uintptr_t klass, uintptr_t id, int *state);
void rpyyarv_const_set(uintptr_t klass, uintptr_t id, uintptr_t val,
                       int *state);
uintptr_t rpyyarv_ivar_get(uintptr_t obj, uintptr_t id, int *state);
void rpyyarv_ivar_set(uintptr_t obj, uintptr_t id, uintptr_t val, int *state);

int rpyyarv_is_class(uintptr_t v);

/* Pin a VALUE for the process lifetime; used for the classes RPyYARV made. */
void rpyyarv_gc_register_mark_object(uintptr_t v);

#ifdef __cplusplus
}
#endif

#endif /* RPYYARV_BOOT_SHIM_H */
