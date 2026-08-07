/*
 * Thin C layer over CRuby APIs an FFI cannot call: macros, the variadic
 * rb_funcall, and anything that may longjmp past the caller's frame.
 * Shared by boot.py (rffi) and test/test_boot_ctypes.py (ctypes).
 */
#ifndef RPYYARV_BOOT_SHIM_H
#define RPYYARV_BOOT_SHIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Boot CRuby and return the main script's compiled ISeq, unexecuted: no
 * ruby_run_node. A wrapper because ruby_init_stack needs an address on the
 * machine stack, or the conservative GC scan range is wrong.
 * NULL when ruby_options yields no ISeq; *status_out is then the exit status.
 */
void *rpyyarv_boot(int argc, char **argv, int *status_out);

int rpyyarv_cleanup(int status);

/* ruby_run_node on the node rpyyarv_boot returned: runs the script under
   CRuby and cleans up, answering the exit status. */
int rpyyarv_run_node(void *n);

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
 * so it is copied to the machine stack first.
 */
uintptr_t rpyyarv_funcallv_id(uintptr_t recv, uintptr_t mid, int argc,
                              const uintptr_t *argv, int *state);
uintptr_t rpyyarv_funcallv(uintptr_t recv, const char *mid, int argc,
                           const uintptr_t *argv, int *state);

/* The same under rb_funcallv_public, for a send with an explicit receiver. */
uintptr_t rpyyarv_funcallv_public_id(uintptr_t recv, uintptr_t mid, int argc,
                                     const uintptr_t *argv, int *state);

/* The toplevel `main`, pinned on first use. */
uintptr_t rpyyarv_top_self(void);

/* Bignum-safe long -> Integer, for fixnum overflow. */
uintptr_t rpyyarv_int2inum(long n);

/* The immediate tags this libruby uses, checked against the compiled-in ones. */
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
 * VALUEs escaped into a foreign heap are invisible to the conservative stack
 * scan. The hook is a GC-rooted TypedData whose dmark calls fn, which marks
 * them with rpyyarv_gc_mark_value. NULL disables it.
 */
void rpyyarv_gc_set_mark_hook(void (*fn)(void));

/* rb_gc_mark on a VALUE; only meaningful while the mark hook is running. */
void rpyyarv_gc_mark_value(uintptr_t v);

void rpyyarv_gc_start(void);

uintptr_t rpyyarv_str_new(const char *s);

/* Both copy their input onto the machine stack first, as funcallv does. */
uintptr_t rpyyarv_ary_new(int n, const uintptr_t *elems);
uintptr_t rpyyarv_str_concat(int n, const uintptr_t *parts);

/* The immediates' classes, fetched once at boot so class_of() needs no rb_*
   call. Slot order is value.py's C_* constants. */
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

/* Object-shape support for dispatch.py's ivar fast path. shape_iv_index
 * answers 1 (found, *index set), 0 (no such ivar) or -1 (fast path unusable),
 * allocating and raising nothing; object_layout reports the RObject layout the
 * RPython side compiles in, so a drifting CRuby is caught at boot. */
#define RPYYARV_LAYOUT_N 6
int rpyyarv_shape_iv_index(unsigned int shape_id, uintptr_t id, int *index);
void rpyyarv_object_layout(int *out);

/* Likewise RArray, for the opt_aref/opt_length fast paths. */
#define RPYYARV_ARRAY_LAYOUT_N 6
void rpyyarv_array_layout(int *out);

/* Array and Range operations, each guarded by rb_protect. */
uintptr_t rpyyarv_ary_resurrect(uintptr_t ary, int *state);
void rpyyarv_ary_store(uintptr_t ary, long idx, uintptr_t val, int *state);
uintptr_t rpyyarv_ary_new_capa(long capa, int *state);
/* Copies elems onto the machine stack first, as funcallv does. */
void rpyyarv_ary_cat(uintptr_t ary, int n, const uintptr_t *elems, int *state);
uintptr_t rpyyarv_range_new(uintptr_t low, uintptr_t high, int excl,
                            int *state);

/* By name, not by ID: libruby exports rb_gv_get/rb_gv_set but not the
 * rb_gvar_* pair the getglobal/setglobal instructions use. */
uintptr_t rpyyarv_gvar_get(const char *name, int *state);
void rpyyarv_gvar_set(const char *name, uintptr_t val, int *state);

/*
 * Calling a CRuby method with a block RPyYARV holds: the one place a CRuby
 * object refers back into RPyYARV, and only through an integer handle, since
 * RPython's GC moves objects and a raw pointer must never reach C. The handle
 * is valid only for the extent of the call.
 */
typedef uintptr_t (*rpyyarv_block_fn)(long handle, int argc,
                                      uintptr_t *argv);
void rpyyarv_set_block_callback(rpyyarv_block_fn fn);
uintptr_t rpyyarv_call_with_block(uintptr_t recv, uintptr_t mid, int argc,
                                  const uintptr_t *argv, long handle,
                                  int *state);

/*
 * The other direction: a method entry in CRuby's own tables that re-enters
 * RPyYARV, so a core method calling back -- to_s, <=>, hash, each -- reaches
 * the definition RPyYARV holds rather than the one CRuby never got.
 *
 * One generic trampoline stands for every such method: it recovers the name
 * with rb_frame_this_func and lets RPyYARV's registry do the lookup, which
 * also keeps redefinition and inheritance right, since nothing is resolved
 * until the call happens. An RPython exception must never cross back into
 * libruby, so a failure comes out through *status and *errval and the shim
 * turns it into a CRuby raise.
 */
#define RPYYARV_TRAMP_OK          0
#define RPYYARV_TRAMP_RAISE       1   /* *errval is the exception to re-raise */
#define RPYYARV_TRAMP_UNSUPPORTED 2   /* *errval is the message String */

typedef uintptr_t (*rpyyarv_tramp_fn)(uintptr_t self, uintptr_t mid, int argc,
                                      uintptr_t *argv, uintptr_t blockproc,
                                      int *status, uintptr_t *errval);
void rpyyarv_set_trampoline_callback(rpyyarv_tramp_fn fn);
void rpyyarv_define_method(uintptr_t klass, uintptr_t mid, int is_private,
                           int *state);

/*
 * A Proc over the same handle, for a block that outlives its call. The handle
 * must stay valid for as long as the Proc can be reached, so RPyYARV's handle
 * table never releases one of these.
 */
uintptr_t rpyyarv_proc_new(long handle, int *state);
int rpyyarv_is_proc(uintptr_t v);

int rpyyarv_is_class(uintptr_t v);

/*
 * The exception a failed rb_protect left behind, cleared on the way out. Must
 * be called on every non-zero *state, or the next raise inherits this one as
 * its cause.
 */
uintptr_t rpyyarv_take_errinfo(void);

/*
 * Install errinfo and answer the previous one. RPyYARV pushes no CRuby frame,
 * so rb_ec_get_errinfo (eval.c) falls back to ec->errinfo; a rescue body has
 * to put `$!` there for a bare `raise` to mean what Ruby says it means.
 */
uintptr_t rpyyarv_swap_errinfo(uintptr_t v);

/* rb_obj_is_kind_of, for checkmatch's rescue clause. */
int rpyyarv_obj_is_kind_of(uintptr_t obj, uintptr_t klass, int *state);

/* ruby_cleanup with an exception pending: CRuby prints it and answers the
   exit status. */
int rpyyarv_cleanup_with_error(uintptr_t err);

/* Hash literals: the ops themselves stay on the funcallv path. */
uintptr_t rpyyarv_hash_new_capa(long capa, int *state);
void rpyyarv_hash_aset(uintptr_t hash, uintptr_t key, uintptr_t val,
                       int *state);
uintptr_t rpyyarv_hash_resurrect(uintptr_t hash, int *state);

/* splatarray: rb_check_to_array, then dup when the flag says so. */
uintptr_t rpyyarv_splat_array(uintptr_t ary, int flag, int *state);

/* rb_mRubyVMFrozenCore, the receiver putspecialobject 1 pushes. */
uintptr_t rpyyarv_vm_core(void);

/* Pin a VALUE for the process lifetime; used for the classes RPyYARV made. */
void rpyyarv_gc_register_mark_object(uintptr_t v);

/* An ArgumentError worded exactly as rb_arity_error_new does; max < 0 is
   CRuby's UNLIMITED_ARGUMENTS. */
uintptr_t rpyyarv_arity_error(int given, int min, int max, int *state);

/*
 * One bit per (class, basic operator) pair whose fast path RPyYARV takes,
 * set when the pair is no longer CRuby's own definition. The pair count is
 * returned above the bits so a caller can refuse a shim it disagrees with.
 */
#define RPYYARV_BOP_COUNT_SHIFT 32
uintptr_t rpyyarv_bop_mask(void);

/*
 * require, resolved the way load.c's search_required does but with the public
 * API only: $LOAD_PATH search, the .rb extension, and the $LOADED_FEATURES
 * index. *path_out is the expanded path on RPYYARV_REQ_RB.
 */
#define RPYYARV_REQ_LOADED   0  /* $LOADED_FEATURES already has it */
#define RPYYARV_REQ_RB       1  /* a .rb file RPyYARV may compile itself */
#define RPYYARV_REQ_FOREIGN  2  /* .so/.bundle, or nowhere on $LOAD_PATH */
int rpyyarv_require_resolve(uintptr_t fname, uintptr_t *path_out, int *state);

/* rb_provide, so a later CRuby require of the same feature is a no-op. */
void rpyyarv_provide(uintptr_t path, int *state);

/* rb_file_absolute_path, for require_relative: RPyYARV pushes no CRuby frame,
   so rb_current_realfilepath cannot name the requiring file. */
uintptr_t rpyyarv_absolute_path(uintptr_t fname, uintptr_t base, int *state);

#ifdef __cplusplus
}
#endif

#endif /* RPYYARV_BOOT_SHIM_H */
