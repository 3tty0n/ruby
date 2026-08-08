/* Thin C layer over CRuby APIs an FFI cannot call: macros, the variadic rb_funcall, and anything that may longjmp past the caller's frame. */
#ifndef RPYYARV_BOOT_SHIM_H
#define RPYYARV_BOOT_SHIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Returns the main script's compiled ISeq unexecuted, NULL with *status_out the exit status; a wrapper because ruby_init_stack needs a machine-stack address or the conservative GC scan range is wrong. */
void *rpyyarv_boot(int argc, char **argv, int *status_out);

int rpyyarv_cleanup(int status);

/* ruby_run_node on rpyyarv_boot's node: runs the script under CRuby and cleans up, answering the exit status. */
int rpyyarv_run_node(void *n);

/* Zero-arg method call guarded by rb_protect. *state is non-zero on raise. */
uintptr_t rpyyarv_call0(uintptr_t recv, const char *mid, int *state);

uintptr_t rpyyarv_intern(const char *name);

uintptr_t rpyyarv_sym_new(const char *name);

/* Largest argc rpyyarv_funcallv* copies onto the machine stack. */
#define RPYYARV_MAX_ARGC 32

/* rb_funcallv under rb_protect; *state is non-zero on raise, -1 when argc exceeds RPYYARV_MAX_ARGC; argv may live in memory CRuby never scans, so it is copied to the machine stack first. */
uintptr_t rpyyarv_funcallv_id(uintptr_t recv, uintptr_t mid, int argc,
                              const uintptr_t *argv, int *state);
uintptr_t rpyyarv_funcallv(uintptr_t recv, const char *mid, int argc,
                           const uintptr_t *argv, int *state);

uintptr_t rpyyarv_funcallv_public_id(uintptr_t recv, uintptr_t mid, int argc,
                                     const uintptr_t *argv, int *state);

/* The toplevel `main`, pinned on first use. */
uintptr_t rpyyarv_top_self(void);

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

const char *rpyyarv_sym_cstr(uintptr_t sym);

/* VALUEs escaped into a foreign heap are invisible to the conservative stack scan: the hook is a GC-rooted TypedData whose dmark calls fn, which marks them with rpyyarv_gc_mark_value; NULL disables it. */
void rpyyarv_gc_set_mark_hook(void (*fn)(void));

/* rb_gc_mark on a VALUE; only meaningful while the mark hook is running. */
void rpyyarv_gc_mark_value(uintptr_t v);

void rpyyarv_gc_start(void);

uintptr_t rpyyarv_str_new(const char *s);

/* Both copy their input onto the machine stack first, as funcallv does. */
uintptr_t rpyyarv_ary_new(int n, const uintptr_t *elems);
uintptr_t rpyyarv_str_concat(int n, const uintptr_t *parts);

/* Fetched once at boot so class_of() needs no rb_* call; slot order is value.py's C_* constants. */
#define RPYYARV_NCLASS 13
void rpyyarv_core_classes(uintptr_t *out);

/* The module a class resolves an instance method through, or Qnil when it has no such method. */
uintptr_t rpyyarv_method_owner(uintptr_t klass, uintptr_t id);

/* Class and object operations, each guarded by rb_protect. */
uintptr_t rpyyarv_define_class(uintptr_t cbase, uintptr_t id, uintptr_t super,
                               int *state);
uintptr_t rpyyarv_class_superclass(uintptr_t klass, int *state);
uintptr_t rpyyarv_singleton_class(uintptr_t obj, int *state);
uintptr_t rpyyarv_obj_alloc(uintptr_t klass, int *state);
uintptr_t rpyyarv_const_get(uintptr_t klass, uintptr_t id, int *state);
void rpyyarv_const_set(uintptr_t klass, uintptr_t id, uintptr_t val,
                       int *state);
uintptr_t rpyyarv_ivar_get(uintptr_t obj, uintptr_t id, int *state);
void rpyyarv_ivar_set(uintptr_t obj, uintptr_t id, uintptr_t val, int *state);

/* shape_iv_index answers 1 (found, *index set), 0 (no such ivar) or -1 (fast path unusable), allocating and raising nothing; object_layout reports the RObject layout the RPython side compiles in, so a drifting CRuby is caught at boot. */
/* The write barrier alone, for an ivar store made by raw word write; wb_direct says whether this build's barrier is the one boot_shim.c vouches for. */
void rpyyarv_obj_written(uintptr_t a, uintptr_t b);
int rpyyarv_wb_direct(void);

#define RPYYARV_LAYOUT_N 7
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

/* By name, not by ID: libruby exports rb_gv_get/rb_gv_set but not the rb_gvar_* pair getglobal/setglobal use. */
uintptr_t rpyyarv_gvar_get(const char *name, int *state);
void rpyyarv_gvar_set(const char *name, uintptr_t val, int *state);

/* A CRuby object refers back into RPyYARV only through an integer handle, since RPython's GC moves objects and a raw pointer must never reach C; the handle is valid only for the extent of the call. */
typedef uintptr_t (*rpyyarv_block_fn)(long handle, int argc,
                                      uintptr_t *argv);
void rpyyarv_set_block_callback(rpyyarv_block_fn fn);
uintptr_t rpyyarv_call_with_block(uintptr_t recv, uintptr_t mid, int argc,
                                  const uintptr_t *argv, long handle,
                                  int *state);

/* A block leaving a CRuby method early cannot unwind as an RPython exception through libruby's frames, so the yielder raises RPyYARV::Unwind (under Exception, not StandardError, so a bare `rescue` cannot eat it) standing in for CRuby's EC_JUMP_TAG (vm_insnhelper.c:1929); every rb_protect boundary below swallows it and leaves *state zero so the RPython side re-raises the parked unwind. */
void rpyyarv_set_block_unwind(void);

/* One generic trampoline re-enters RPyYARV for every method entry in CRuby's tables, resolving the name with rb_frame_this_func at call time so redefinition and inheritance stay right; an RPython exception must never cross back into libruby, so failures come out through *status and *errval for the shim to raise. */
#define RPYYARV_TRAMP_OK          0
#define RPYYARV_TRAMP_RAISE       1   /* *errval is the exception to re-raise */
#define RPYYARV_TRAMP_UNSUPPORTED 2   /* *errval is the message String */
#define RPYYARV_TRAMP_UNWIND      3   /* an unwind parked on the RPython side */

typedef uintptr_t (*rpyyarv_tramp_fn)(uintptr_t self, uintptr_t mid, int argc,
                                      uintptr_t *argv, uintptr_t blockproc,
                                      int *status, uintptr_t *errval);
void rpyyarv_set_trampoline_callback(rpyyarv_tramp_fn fn);
void rpyyarv_define_method(uintptr_t klass, uintptr_t mid, int is_private,
                           int *state);

/* A Proc over the same handle: it must stay valid as long as the Proc is reachable, so RPyYARV's handle table never releases one of these. */
uintptr_t rpyyarv_proc_new(long handle, int *state);
int rpyyarv_is_proc(uintptr_t v);

int rpyyarv_is_class(uintptr_t v);

/* The exception a failed rb_protect left behind, cleared on the way out; must be called on every non-zero *state or the next raise inherits this one as its cause. */
uintptr_t rpyyarv_take_errinfo(void);

/* RPyYARV pushes no CRuby frame, so rb_ec_get_errinfo (eval.c) falls back to ec->errinfo; a rescue body must put `$!` there for a bare `raise` to work. */
uintptr_t rpyyarv_swap_errinfo(uintptr_t v);

/* make_localjump_error (vm.c:2175); reason is a ruby_tag_type. */
uintptr_t rpyyarv_local_jump_error(const char *mesg, uintptr_t value,
                                   int reason, int *state);

int rpyyarv_obj_is_kind_of(uintptr_t obj, uintptr_t klass, int *state);

/* ruby_cleanup with an exception pending: CRuby prints it and answers the exit status. */
int rpyyarv_cleanup_with_error(uintptr_t err);

/* Hash literals: the ops themselves stay on the funcallv path. */
uintptr_t rpyyarv_hash_new_capa(long capa, int *state);
void rpyyarv_hash_aset(uintptr_t hash, uintptr_t key, uintptr_t val,
                       int *state);
uintptr_t rpyyarv_hash_resurrect(uintptr_t hash, int *state);

uintptr_t rpyyarv_splat_array(uintptr_t ary, int flag, int *state);

/* rb_mRubyVMFrozenCore, the receiver putspecialobject 1 pushes. */
uintptr_t rpyyarv_vm_core(void);

/* Pin a VALUE for the process lifetime; used for the classes RPyYARV made. */
void rpyyarv_gc_register_mark_object(uintptr_t v);

/* An ArgumentError worded exactly as rb_arity_error_new does; max < 0 is CRuby's UNLIMITED_ARGUMENTS. */
uintptr_t rpyyarv_arity_error(int given, int min, int max, int *state);

/* One bit per (class, basic operator) pair, set when the pair is no longer CRuby's own definition; the pair count rides above the bits so a caller can refuse a shim it disagrees with. */
#define RPYYARV_BOP_COUNT_SHIFT 32
uintptr_t rpyyarv_bop_mask(void);

/* One field of a direct Range instance, or Qundef for anything else. */
#define RPYYARV_RANGE_BEG  0
#define RPYYARV_RANGE_END  1
#define RPYYARV_RANGE_EXCL 2
uintptr_t rpyyarv_range_part(uintptr_t range, int which);

/* Resolved the way load.c's search_required does but with the public API only; *path_out is the expanded path on RPYYARV_REQ_RB. */
#define RPYYARV_REQ_LOADED   0  /* $LOADED_FEATURES already has it */
#define RPYYARV_REQ_RB       1  /* a .rb file RPyYARV may compile itself */
#define RPYYARV_REQ_FOREIGN  2  /* .so/.bundle, or nowhere on $LOAD_PATH */
int rpyyarv_require_resolve(uintptr_t fname, uintptr_t *path_out, int *state);

/* rb_provide, so a later CRuby require of the same feature is a no-op. */
void rpyyarv_provide(uintptr_t path, int *state);

/* For require_relative: RPyYARV pushes no CRuby frame, so rb_current_realfilepath cannot name the requiring file. */
uintptr_t rpyyarv_absolute_path(uintptr_t fname, uintptr_t base, int *state);

#ifdef __cplusplus
}
#endif

#endif /* RPYYARV_BOOT_SHIM_H */
