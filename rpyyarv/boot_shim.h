/* Thin C layer over CRuby macros, variadics, and anything that may longjmp. */
#ifndef RPYYARV_BOOT_SHIM_H
#define RPYYARV_BOOT_SHIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Compiled ISeq unexecuted; ruby_init_stack needs a machine-stack address. */
void *rpyyarv_boot(int argc, char **argv, int *status_out);

int rpyyarv_cleanup(int status);

/* Serialize foreign Ractor entries without waiting under CRuby's VM lock. */
void rpyyarv_set_thread_callbacks(void (*enter)(void), void (*leave)(void),
                                  void (*acquire)(void),
                                  void (*release)(void));
void rpyyarv_activate_threads(void);
int rpyyarv_ractor_class_p(uintptr_t value);
int rpyyarv_ractor_p(uintptr_t value);
int rpyyarv_ractor_callback_p(void);
int rpyyarv_native_ractors_p(void);
void rpyyarv_native_ractors_poll(uintptr_t waited);

/* ruby_run_node on the boot node: runs under CRuby, cleans up, exit status. */
int rpyyarv_run_node(void *n);

/* Zero-arg method call guarded by rb_protect. *state is non-zero on raise. */
uintptr_t rpyyarv_call0(uintptr_t recv, const char *mid, int *state);

uintptr_t rpyyarv_intern(const char *name);

uintptr_t rpyyarv_sym_new(const char *name);

/* $~ or one of its captures from the active CRuby frame. */
uintptr_t rpyyarv_getspecial(int type, int *state);

uintptr_t rpyyarv_str_intern(uintptr_t str, int *state);

uintptr_t rpyyarv_str_ord(uintptr_t str);

uintptr_t rpyyarv_str_char_at(uintptr_t str, uintptr_t idx);

uintptr_t rpyyarv_toregexp(int opt, int n, const uintptr_t *parts,
                           int *state);

/* Largest argc rpyyarv_funcallv* copies onto the machine stack. */
#define RPYYARV_MAX_ARGC 256

/* rb_funcallv under rb_protect; argv is copied to the machine stack first. */
uintptr_t rpyyarv_funcallv_id(uintptr_t recv, uintptr_t mid, int argc,
                              const uintptr_t *argv, int *state);
uintptr_t rpyyarv_funcallv_id_blocking(uintptr_t recv, uintptr_t mid, int argc,
                                       const uintptr_t *argv, int *state);
uintptr_t rpyyarv_funcallv(uintptr_t recv, const char *mid, int argc,
                           const uintptr_t *argv, int *state);

uintptr_t rpyyarv_funcallv_public_id(uintptr_t recv, uintptr_t mid, int argc,
                                     const uintptr_t *argv, int *state);
uintptr_t rpyyarv_funcallv_public_id_blocking(uintptr_t recv, uintptr_t mid,
                                              int argc,
                                              const uintptr_t *argv,
                                              int *state);

/* The last argument must be a Hash; it reaches the callee as keywords. */
uintptr_t rpyyarv_funcallv_kw_id(uintptr_t recv, uintptr_t mid, int argc,
                                 const uintptr_t *argv, int pub, int *state);

/* The toplevel `main`, pinned on first use. */
uintptr_t rpyyarv_top_self(void);

uintptr_t rpyyarv_int2inum(long n);

/* The immediate tags this libruby uses, checked against compiled-in ones. */
void rpyyarv_special_consts(uintptr_t *qfalse, uintptr_t *qnil,
                            uintptr_t *qtrue, uintptr_t *fixnum_flag);

/* rb_iseq_t is incomplete here, so the ISeq crosses the FFI as void *. */
uintptr_t rpyyarv_iseqw_new(void *iseq);
void *rpyyarv_iseqw_ptr(uintptr_t iseqw);
uintptr_t rpyyarv_iseqw_children(uintptr_t iseqw);
long rpyyarv_iseqw_child_index(uintptr_t children, uintptr_t ary, long hint);
void *rb_rpyyarv_cref_new(const void *outer, uintptr_t klass, int by_eval);

long      rpyyarv_str_len(uintptr_t str);
const char *rpyyarv_str_ptr(uintptr_t str);
const char *rpyyarv_inspect_cstr(uintptr_t obj);

long      rpyyarv_ary_len(uintptr_t ary);
uintptr_t rpyyarv_ary_entry(uintptr_t ary, long idx);

int rpyyarv_is_array(uintptr_t v);
void rpyyarv_patch_method_equality(void);
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

/* Escaped VALUEs are invisible to the stack scan; a TypedData dmark marks. */
void rpyyarv_gc_set_mark_hook(void (*fn)(void));

/* rb_gc_mark on a VALUE; only meaningful while the mark hook is running. */
void rpyyarv_gc_mark_value(uintptr_t v);

/* rb_gc_mark_maybe on a word that may not be a VALUE; jitframes use it. */
void rpyyarv_gc_mark_maybe(uintptr_t v);

uintptr_t rpyyarv_int_to_s(uintptr_t v);
uintptr_t rpyyarv_str_gsub2(uintptr_t str, uintptr_t pat, uintptr_t rep,
                            uintptr_t mid, int *state);
uintptr_t rpyyarv_str_casecmp(uintptr_t a, uintptr_t b);
uintptr_t rpyyarv_str_cmp(uintptr_t a, uintptr_t b);
uintptr_t rpyyarv_str_downcase(uintptr_t s);
uintptr_t rpyyarv_str_downcase_bang(uintptr_t s);
uintptr_t rpyyarv_str_upcase(uintptr_t s);
uintptr_t rpyyarv_str_upcase_bang(uintptr_t s);
uintptr_t rpyyarv_sym_to_s(uintptr_t v);
uintptr_t rpyyarv_str_dup(uintptr_t v);
uintptr_t rpyyarv_str_length(uintptr_t v);
uintptr_t rpyyarv_str_tr1(uintptr_t str, uintptr_t from, uintptr_t to);
uintptr_t rpyyarv_str_index_of(uintptr_t str, uintptr_t needle);
uintptr_t rpyyarv_str_match_p(uintptr_t str, uintptr_t re, int *state);
uintptr_t rpyyarv_str_eq_tilde(uintptr_t a, uintptr_t b, int *state);
uintptr_t rpyyarv_reg_eqq(uintptr_t re, uintptr_t str, int *state);
uintptr_t rpyyarv_last_match0(void);
uintptr_t rpyyarv_last_match1(uintptr_t n);
uintptr_t rpyyarv_str_match(uintptr_t str, uintptr_t re, int *state);
uintptr_t rpyyarv_str_empty_p(uintptr_t v);
uintptr_t rpyyarv_hash_empty_p(uintptr_t v);
uintptr_t rpyyarv_str_uminus(uintptr_t v);
uintptr_t rpyyarv_ary_pop_fast(uintptr_t v);
uintptr_t rpyyarv_ary_push1(uintptr_t v, uintptr_t elt);
uintptr_t rpyyarv_ary_shift_fast(uintptr_t v);
uintptr_t rpyyarv_ary_unshift1(uintptr_t v, uintptr_t elt);
uintptr_t rpyyarv_obj_freeze(uintptr_t v);
uintptr_t rpyyarv_ary_hash_freeze(uintptr_t v);
uintptr_t rpyyarv_hash_keys_fast(uintptr_t hash, int *state);
uintptr_t rpyyarv_ary_flatten_bang1(uintptr_t v);
uintptr_t rpyyarv_ss_pos(uintptr_t v);
uintptr_t rpyyarv_ss_set_pos(uintptr_t v, uintptr_t posv);
uintptr_t rpyyarv_ss_eos_p(uintptr_t v);
uintptr_t rpyyarv_ss_matched_size(uintptr_t v);
uintptr_t rpyyarv_ss_skip(uintptr_t v, uintptr_t re, int *state);
uintptr_t rpyyarv_str_byteslice2(uintptr_t str, uintptr_t begv, uintptr_t lenv);
uintptr_t rpyyarv_str_force_encoding_fast(uintptr_t str, uintptr_t enc);
uintptr_t rpyyarv_unpack1_double(uintptr_t str, uintptr_t fmt, uintptr_t offv);
uintptr_t rpyyarv_str_ascii_only_p(uintptr_t str);
uintptr_t rpyyarv_pack_double_into(uintptr_t ary, uintptr_t fmt, uintptr_t buf);

/* Kernel#format: rb_str_format(argc, argv, fmt) under rb_protect. */
uintptr_t rpyyarv_sprintf(int argc, const uintptr_t *argv, uintptr_t fmt,
                          int *state);
/* CGI.escapeHTML for a String; Qundef for anything else. */
uintptr_t rpyyarv_cgi_escape_html(uintptr_t str);
/* String#match? unprotected, only if the search cannot raise (boot_shim.c). */
uintptr_t rpyyarv_str_match_p_fast(uintptr_t str, uintptr_t re);

/* RUBY_FATAL_FIBER_KILLED, the errinfo a killed fiber unwinds with. */
uintptr_t rpyyarv_fiber_killed_value(void);

/* 0 unless v is the fiber kill, which never returns: a fatal unwind. */
int rpyyarv_rethrow_if_fiber_kill(uintptr_t v);

/* One fiber switch: park returns the copy-into buffer, unpark copy-from. */
typedef void *(*rpyyarv_fiber_save_fn)(long key);
/* unpark/born get the arriving stack's bounds for the stack-depth window. */
typedef void *(*rpyyarv_fiber_arrive_fn)(long key, long stack_base, long stack_size);
typedef void (*rpyyarv_fiber_born_fn)(long key, long stack_base, long stack_size);
typedef void (*rpyyarv_fiber_key_fn)(long key);
/* base_slot/top_slot: addresses of RPython's shadowstack base and top. */
void rpyyarv_set_fiber_hooks(rpyyarv_fiber_save_fn park,
                             rpyyarv_fiber_arrive_fn unpark,
                             rpyyarv_fiber_born_fn born,
                             rpyyarv_fiber_key_fn died,
                             void **base_slot, void **top_slot);

/* From the handle owner's dmark: block frames live as long as the Proc. */
typedef void (*rpyyarv_handle_mark_fn)(long handle);
void rpyyarv_set_handle_mark_callback(rpyyarv_handle_mark_fn fn);

/* From rb_clear_constant_cache_for_id; RPyYARV invalidates its cache whole. */
void rpyyarv_set_const_hook(void (*fn)(void));

/* From rb_clear_method_cache: CRuby's funnel for def/undef/alias/include. */
void rpyyarv_set_method_hook(void (*fn)(uintptr_t, uintptr_t));

void rpyyarv_gc_start(void);

uintptr_t rpyyarv_str_new(const char *s, long n);

/* Both copy their input onto the machine stack first, as funcallv does. */
uintptr_t rpyyarv_ary_new(int n, const uintptr_t *elems);
uintptr_t rpyyarv_ary_subseq(uintptr_t ary, long beg, long len);
uintptr_t rpyyarv_str_concat(int n, const uintptr_t *parts);

/* Fetched once at boot; slot order is value.py's C_* constants. */
#define RPYYARV_NCLASS 14
void rpyyarv_core_classes(uintptr_t *out);

/* The module a class resolves an instance method through, or Qnil. */
uintptr_t rpyyarv_method_owner(uintptr_t klass, uintptr_t id);

/* The module `super` from owner's id reaches next along klass's chain. */
uintptr_t rpyyarv_super_owner(uintptr_t klass, uintptr_t owner, uintptr_t id);

/* Module#<=: 1 klass is target or below, 0 not, -1 not a module. */
int rpyyarv_class_le(uintptr_t klass, uintptr_t target);

/* respond_to? for every instance of klass: 1 yes, 0 no, -1 receiver only. */
int rpyyarv_responds(uintptr_t klass, uintptr_t sym);

/* rb_ary_to_ary: what expandarray expands a non-Array into. */
uintptr_t rpyyarv_ary_to_ary(uintptr_t obj, int *state);

/* The self of the frame running now; a yield can spot instance_eval's swap. */
uintptr_t rpyyarv_current_receiver(void);

/* The frozen String Symbol#name returns, or Qundef for a dynamic symbol. */
uintptr_t rpyyarv_sym_name(uintptr_t sym);

/* dirname(realpath(path)), what __dir__ answers; Qundef without a realpath. */
uintptr_t rpyyarv_dir_of(uintptr_t path);

/* Class variables against the caller's cbase; *state non-zero on raise. */
uintptr_t rpyyarv_cvar_get(uintptr_t klass, uintptr_t id, int *state);
void rpyyarv_cvar_set(uintptr_t klass, uintptr_t id, uintptr_t val, int *state);
int rpyyarv_cvar_defined(uintptr_t klass, uintptr_t id);
int rpyyarv_is_singleton_class(uintptr_t klass);

/* String#<< of two Strings of one encoding; else Qundef (rb_str_concat). */
uintptr_t rpyyarv_str_append(uintptr_t str, uintptr_t other);

/* The method after owner's along klass's chain; Qundef when there is none. */
uintptr_t rpyyarv_call_super(uintptr_t klass, uintptr_t owner, uintptr_t recv,
                             uintptr_t id, int argc, const uintptr_t *argv,
                             int kw, uintptr_t proc, int *state);

/* The heap Float flonums cannot hold, plus the RFloat layout value.py reads. */
uintptr_t rpyyarv_float_new(double d);
void rpyyarv_float_layout(int *out);

/* Class and object operations, each guarded by rb_protect. */
uintptr_t rpyyarv_define_module(uintptr_t cbase, uintptr_t id, int *state);
uintptr_t rpyyarv_define_class(uintptr_t cbase, uintptr_t id, uintptr_t super,
                               int *state);
uintptr_t rpyyarv_class_superclass(uintptr_t klass, int *state);
uintptr_t rpyyarv_singleton_class(uintptr_t obj, int *state);
uintptr_t rpyyarv_obj_alloc(uintptr_t klass, int *state);
uintptr_t rpyyarv_obj_alloc_fast(uintptr_t klass);
uintptr_t rpyyarv_alloc_default(uintptr_t klass);
uintptr_t rpyyarv_const_get(uintptr_t klass, uintptr_t id, int *state);
uintptr_t rpyyarv_const_get_from(uintptr_t klass, uintptr_t id, int *state);
uintptr_t rpyyarv_const_at(uintptr_t klass, uintptr_t id, int *state);
void rpyyarv_const_set(uintptr_t klass, uintptr_t id, uintptr_t val,
                       int *state);
uintptr_t rpyyarv_ivar_get(uintptr_t obj, uintptr_t id, int *state);
void rpyyarv_ivar_set(uintptr_t obj, uintptr_t id, uintptr_t val, int *state);

/* shape_iv_index: 1 found, 0 absent, -1 no fast path, allocating nothing. */
/* Write barrier alone for a raw-word ivar store; wb_direct vouches for it. */
void rpyyarv_obj_written(uintptr_t a, uintptr_t b);
int rpyyarv_wb_direct(void);

#define RPYYARV_LAYOUT_N 12
int rpyyarv_shape_iv_index(unsigned int shape_id, uintptr_t id, int *index);
void rpyyarv_object_layout(int *out);

/* 1 when a raw store to *index plus a raw write of `after` can add `id`. */
int rpyyarv_shape_add_ivar_fits(unsigned int before, unsigned int after,
                                uintptr_t id, int *index);

/* Likewise RArray, for the opt_aref/opt_aset/opt_length fast paths. */
#define RPYYARV_ARRAY_LAYOUT_N 10
void rpyyarv_array_layout(int *out);
void rpyyarv_struct_layout(int *out);

/* rb_str_equal's String-argument half, which neither allocates nor raises. */
uintptr_t rpyyarv_str_eq(uintptr_t a, uintptr_t b);

/* Array and Range operations, each guarded by rb_protect. */
uintptr_t rpyyarv_ary_resurrect(uintptr_t ary, int *state);
void rpyyarv_ary_store(uintptr_t ary, long idx, uintptr_t val, int *state);
uintptr_t rpyyarv_ary_new_capa(long capa, int *state);
uintptr_t rpyyarv_ary_new_filled(long len, uintptr_t val, int *state);
void rpyyarv_ary_store_fresh(uintptr_t ary, long idx, uintptr_t val);
uintptr_t rpyyarv_ary_new_capa_fast(long capa);
uintptr_t rpyyarv_ary_new_filled_fast(long len, uintptr_t val);
/* Copies elems onto the machine stack first, as funcallv does. */
void rpyyarv_ary_cat(uintptr_t ary, int n, const uintptr_t *elems, int *state);
uintptr_t rpyyarv_range_new(uintptr_t low, uintptr_t high, int excl,
                            int *state);

/* By name, not by ID: libruby exports rb_gv_get/rb_gv_set, not rb_gvar_*. */
uintptr_t rpyyarv_gvar_get(const char *name, int *state);
void rpyyarv_gvar_set(const char *name, uintptr_t val, int *state);

/* An integer handle, not a pointer: RPython's GC moves objects. */
/* bowner/bmid: the bmethod identity when the proc runs as one, else Qnil/0. */
typedef uintptr_t (*rpyyarv_block_fn)(long handle, int argc,
                                      uintptr_t *argv, uintptr_t sub_self,
                                      uintptr_t bowner, uintptr_t bmid);
void rpyyarv_set_block_callback(rpyyarv_block_fn fn);
/* kw != 0 means the last argument is a Hash the callee takes as keywords. */
uintptr_t rpyyarv_call_with_block(uintptr_t recv, uintptr_t mid, int argc,
                                  const uintptr_t *argv, long handle,
                                  void *native_iseq, void *native_cref,
                                  int kw, int *state);
/* Same, for a block that is already a CRuby Proc: it goes through as itself. */
uintptr_t rpyyarv_call_with_proc(uintptr_t recv, uintptr_t mid, int argc,
                                 const uintptr_t *argv, uintptr_t proc, int kw,
                                 int *state);

/* Early exit raises RPyYARV::Unwind for EC_JUMP_TAG (vm_insnhelper.c:1929). */
void rpyyarv_set_block_unwind(void);

/* No RPython exception may cross into libruby; failures use *status. */
#define RPYYARV_TRAMP_OK          0
#define RPYYARV_TRAMP_RAISE       1   /* *errval is the exception to re-raise */
#define RPYYARV_TRAMP_UNSUPPORTED 2   /* *errval is the message String */
#define RPYYARV_TRAMP_UNWIND      3   /* an unwind parked on the RPython side */
#define RPYYARV_TRAMP_JUMPTAG     4   /* a tag caught in a yield, to re-issue */

typedef uintptr_t (*rpyyarv_tramp_fn)(uintptr_t self, uintptr_t mid,
                                      uintptr_t owner, uintptr_t defkey,
                                      int argc,
                                      uintptr_t *argv, uintptr_t blockproc,
                                      int kw, int *status, uintptr_t *errval);
void rpyyarv_set_trampoline_callback(rpyyarv_tramp_fn fn);
uintptr_t rpyyarv_define_method(uintptr_t klass, uintptr_t mid, int visibility,
                                void *native_iseq, void *native_cref,
                                int *state);

/* The handle must outlive the Proc, so the handle table never releases it. */
uintptr_t rpyyarv_proc_new(long handle, int *state);

/* One handle whose GC owner died, or -1 when none are pending. */
long rpyyarv_pop_dead_handle(void);
uintptr_t rpyyarv_block_sentinel(void);
long rpyyarv_proc_handle(uintptr_t v);
const char *rpyyarv_id_name(uintptr_t id);
int rpyyarv_kw_hash_p(uintptr_t h);
uintptr_t rpyyarv_kw_hash_dup(uintptr_t h, int *state);

uintptr_t rpyyarv_hash_aref_v(uintptr_t hash, uintptr_t key, int *state);
uintptr_t rpyyarv_set_include(uintptr_t set, uintptr_t elt, int *state);
uintptr_t rpyyarv_hash_pairs(uintptr_t hash, int *state);
uintptr_t rpyyarv_alias_variable(uintptr_t sym1, uintptr_t sym2, int *state);
uintptr_t rpyyarv_hash_lookup_fast(uintptr_t hash, uintptr_t key);
uintptr_t rpyyarv_hash_aset_fast(uintptr_t hash, uintptr_t key, uintptr_t val);
uintptr_t rpyyarv_str_push(uintptr_t str, uintptr_t other, int *state);
uintptr_t rpyyarv_str_start_with(uintptr_t str, uintptr_t prefix);
int rpyyarv_is_proc(uintptr_t v);

int rpyyarv_is_class(uintptr_t v);

/* Call on every non-zero *state or the next raise inherits this as cause. */
uintptr_t rpyyarv_take_errinfo(void);

/* rb_ec_get_errinfo (eval.c) falls back to ec->errinfo; `$!` must go there. */
uintptr_t rpyyarv_swap_errinfo(uintptr_t v);

/* make_localjump_error (vm.c:2175); reason is a ruby_tag_type. */
uintptr_t rpyyarv_local_jump_error(const char *mesg, uintptr_t value,
                                   int reason, int *state);

int rpyyarv_obj_is_kind_of(uintptr_t obj, uintptr_t klass, int *state);

/* ruby_cleanup with an exception pending: CRuby prints it, gives status. */
int rpyyarv_cleanup_with_error(uintptr_t err);

/* Hash literals: the ops themselves stay on the funcallv path. */
uintptr_t rpyyarv_hash_new_capa(long capa, int *state);
void rpyyarv_hash_aset(uintptr_t hash, uintptr_t key, uintptr_t val,
                       int *state);
uintptr_t rpyyarv_hash_resurrect(uintptr_t hash, int *state);

/* A **splat's Hash; lookup answers Qundef for an absent key. */
long rpyyarv_hash_size(uintptr_t hash);
uintptr_t rpyyarv_hash_lookup(uintptr_t hash, uintptr_t key, int *state);
void rpyyarv_hash_delete(uintptr_t hash, uintptr_t key, int *state);
uintptr_t rpyyarv_hash_keys(uintptr_t hash, int *state);
/* vm_caller_setup_keyword_hash: a ** that is not a Hash goes to to_hash. */
uintptr_t rpyyarv_to_hash_type(uintptr_t v, int *state);

uintptr_t rpyyarv_splat_array(uintptr_t ary, int flag, int *state);

/* vm_concat_array (to == 0) and vm_concat_to_array (to != 0). */
uintptr_t rpyyarv_concat_array(uintptr_t ary1, uintptr_t ary2, int to,
                               int *state);

/* rb_mRubyVMFrozenCore, the receiver putspecialobject 1 pushes. */
uintptr_t rpyyarv_vm_core(void);

/* Pin a VALUE for the process lifetime; used for the classes RPyYARV made. */
void rpyyarv_gc_register_mark_object(uintptr_t v);

/* ArgumentError as rb_arity_error_new words it; max < 0 is unlimited. */
uintptr_t rpyyarv_arity_error(int given, int min, int max, int *state);

/* kind is "missing" or "unknown"; keys is an Array of Symbols. */
uintptr_t rpyyarv_keyword_error(const char *kind, uintptr_t keys, int *state);

/* One bit per (class, basic operator) pair redefined; count rides above. */
uintptr_t rpyyarv_bop_mask(int *count);

/* One field of a direct Range instance, or Qundef for anything else. */
#define RPYYARV_RANGE_BEG  0
#define RPYYARV_RANGE_END  1
#define RPYYARV_RANGE_EXCL 2
uintptr_t rpyyarv_range_part(uintptr_t range, int which);
int rpyyarv_struct_member_index(uintptr_t klass, uintptr_t id);
uintptr_t rpyyarv_struct_get(uintptr_t obj, int index);
void rpyyarv_struct_set(uintptr_t obj, int index, uintptr_t value);
long rpyyarv_struct_arity(uintptr_t klass);
uintptr_t rpyyarv_struct_alloc(uintptr_t klass);
uintptr_t rpyyarv_yield_values(int argc, const uintptr_t *argv, int kw,
                               int *state);
uintptr_t rpyyarv_class_ivar_get(uintptr_t obj, uintptr_t id);
int rpyyarv_ivar_defined(uintptr_t obj, uintptr_t id);
int rpyyarv_const_defined(uintptr_t klass, uintptr_t id, int inherit);
int rpyyarv_method_defined(uintptr_t obj, uintptr_t id, int include_private);
uintptr_t rpyyarv_str_getbyte(uintptr_t str, uintptr_t index);
uintptr_t rpyyarv_str_setbyte(uintptr_t str, uintptr_t index, uintptr_t value);

/* As load.c's search_required, public API only; *path_out on REQ_RB. */
#define RPYYARV_REQ_LOADED   0  /* $LOADED_FEATURES already has it */
#define RPYYARV_REQ_RB       1  /* a .rb file RPyYARV may compile itself */
#define RPYYARV_REQ_FOREIGN  2  /* .so/.bundle, or nowhere on $LOAD_PATH */
int rpyyarv_require_resolve(uintptr_t fname, uintptr_t *path_out, int *state);

/* rb_provide, so a later CRuby require of the same feature is a no-op. */
void rpyyarv_provide(uintptr_t path, int *state);

/* RPyYARV pushes no CRuby frame: rb_current_realfilepath cannot name it. */
uintptr_t rpyyarv_absolute_path(uintptr_t fname, uintptr_t base, int *state);

#ifdef __cplusplus
}
#endif

#endif /* RPYYARV_BOOT_SHIM_H */
