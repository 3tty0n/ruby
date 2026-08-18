#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include <locale.h>
#include <ruby.h>
#include <ruby/re.h>

/* In-tree, so the object-shape API libruby does not export is still reachable. */
#include "shape.h"
#include "internal/array.h"
/* Its STATIC_ASSERTs are what let the RPython ivar fast path read an imemo/fields with the RObject layout. */
#include "internal/imemo.h"
#include "internal/numeric.h"
#include "internal/range.h"
/* rb_str_eql_internal, which YJIT relies on to neither allocate nor raise. */
#include "internal/string.h"
/* rb_hrtime_t, for reading a Regexp's own onigmo timelimit alongside the process-global one. */
#include "hrtime.h"
#include "rpyyarv.h"

#include "boot_shim.h"

/* From the internal iseq.h, redeclared to avoid pulling in vm_core.h. */
struct rb_iseq_struct;
VALUE rb_iseqw_new(const struct rb_iseq_struct *iseq);

static int block_unwind;

/* RPyYARV::Unwind carries a parked unwind across libruby's C frames; under Exception so no bare `rescue` can eat it. */
static VALUE
unwind_class(void)
{
    static VALUE klass = Qundef;
    if (klass == Qundef) {
        VALUE mod = rb_define_module("RPyYARV");
        klass = rb_define_class_under(mod, "Unwind", rb_eException);
        rb_gc_register_mark_object(klass);
    }
    return klass;
}

void
rpyyarv_set_block_unwind(void)
{
    block_unwind = 1;
}

/* internal/thread.h's RUBY_FATAL_FIBER_KILLED, spelled out rather than pulling that header in here. */
#define RPYYARV_FIBER_KILLED RB_INT2FIX(2)

/* A failed rb_protect whose exception is the carrier: the RPython side holds the real unwind, so report success. */
static void
absorb_unwind(int *state)
{
    VALUE err;
    if (!*state) return;
    err = rb_errinfo();
    if (!NIL_P(err) && rb_obj_is_kind_of(err, unwind_class())) {
        rb_set_errinfo(Qnil);
        *state = 0;
    }
}

/* Fiber#kill arrives as a TAG_FATAL rb_protect failure, which RPyYARV carries as an ordinary raise so its ensures run; at the last of its frames it goes back to being fatal, since no rescue may see it and the fiber has to die. */
uintptr_t
rpyyarv_fiber_killed_value(void)
{
    return (uintptr_t)RPYYARV_FIBER_KILLED;
}

int
rpyyarv_rethrow_if_fiber_kill(uintptr_t v)
{
    if ((VALUE)v != RPYYARV_FIBER_KILLED) return 0;
    rb_rpyyarv_fiber_kill_rethrow();
    return 1;                     /* not reached */
}

void *
rpyyarv_boot(int argc, char **argv, int *status_out)
{
    /* On the machine stack: ruby_init_stack records its address as the lower bound of the conservative GC scan. */
    VALUE variable_in_this_stack_frame;

    /* main.c does this before ruby_sysinit; without it the locale encoding is US-ASCII. */
    setlocale(LC_CTYPE, "");

    ruby_sysinit(&argc, &argv);
    ruby_init_stack(&variable_in_this_stack_frame);
    ruby_init();

    void *n = ruby_options(argc, argv);

    /* --version, --help and syntax errors answer a VALUE, not an ISeq. */
    int status = 0;
    if (!ruby_executable_node(n, &status)) {
        *status_out = status;
        return NULL;
    }
    *status_out = 0;
    return n;
}

int
rpyyarv_cleanup(int status)
{
    return ruby_cleanup(status);
}

/* rpyyarv_boot's node is ISEQ_TYPE_MAIN, which vm_set_top_stack (vm.c:888) refuses to eval. */
int
rpyyarv_run_node(void *n)
{
    return ruby_run_node(n);
}

struct call0_args {
    VALUE recv;
    ID    mid;
};

static VALUE
call0_body(VALUE argp)
{
    struct call0_args *a = (struct call0_args *)argp;
    return rb_funcallv(a->recv, a->mid, 0, NULL);
}

uintptr_t
rpyyarv_call0(uintptr_t recv, const char *mid, int *state)
{
    struct call0_args a;
    a.recv = (VALUE)recv;
    a.mid  = rb_intern(mid);

    *state = 0;
    VALUE r = rb_protect(call0_body, (VALUE)&a, state);
    absorb_unwind(state);
    if (*state) {
        /* Clear it, or the next call re-raises. */
        rb_set_errinfo(Qnil);
        return (uintptr_t)Qnil;
    }
    return (uintptr_t)r;
}

uintptr_t
rpyyarv_intern(const char *name)
{
    return (uintptr_t)rb_intern(name);
}

uintptr_t
rpyyarv_sym_new(const char *name)
{
    return (uintptr_t)ID2SYM(rb_intern(name));
}

static VALUE
getspecial_body(VALUE type)
{
    VALUE backref = rb_backref_get();
    int t = FIX2INT(type);

    if (t == 0) return backref;
    if (!(t & 1)) return rb_reg_nth_match(t >> 1, backref);
    switch (t >> 1) {
      case '&': return rb_reg_last_match(backref);
      case '`': return rb_reg_match_pre(backref);
      case '\'': return rb_reg_match_post(backref);
      case '+': return rb_reg_match_last(backref);
      default: rb_bug("unexpected back-ref");
    }
}

uintptr_t
rpyyarv_getspecial(int type, int *state)
{
    *state = 0;
    VALUE r = rb_protect(getspecial_body, INT2FIX(type), state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
str_intern_body(VALUE str)
{
    return rb_str_intern(str);
}

uintptr_t
rpyyarv_str_intern(uintptr_t str, int *state)
{
    *state = 0;
    VALUE r = rb_protect(str_intern_body, (VALUE)str, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

struct toregexp_args {
    int opt;
    int n;
    const VALUE *parts;
};

static VALUE
toregexp_body(VALUE argp)
{
    struct toregexp_args *a = (struct toregexp_args *)argp;
    VALUE src;
    VALUE re;
    int i;

    if (a->n == 0) rb_raise(rb_eArgError, "no arguments given");
    src = rb_str_new3(a->parts[0]);
    for (i = 1; i < a->n; i++) rb_str_buf_append(src, a->parts[i]);
    re = rb_reg_new_str(src, a->opt);
    return rb_obj_freeze(re);
}

uintptr_t
rpyyarv_toregexp(int opt, int n, const uintptr_t *parts, int *state)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    struct toregexp_args a;
    int i;

    if (n < 0 || n > RPYYARV_MAX_ARGC) {
        *state = -1;
        return (uintptr_t)Qnil;
    }
    for (i = 0; i < n; i++) buf[i] = (VALUE)parts[i];
    a.opt = opt;
    a.n = n;
    a.parts = buf;
    *state = 0;
    VALUE r = rb_protect(toregexp_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

struct funcallv_args {
    VALUE recv;
    ID    mid;
    int   argc;
    const VALUE *argv;
    int   pub;
};

static VALUE
funcallv_body(VALUE argp)
{
    struct funcallv_args *a = (struct funcallv_args *)argp;
    return rb_funcallv(a->recv, a->mid, a->argc, a->argv);
}

uintptr_t
rpyyarv_funcallv_id(uintptr_t recv, uintptr_t mid, int argc,
                    const uintptr_t *argv, int *state)
{
    /* On the machine stack, so the conservative scan covers the arguments until rb_funcallv copies them onto the VM stack. */
    VALUE buf[RPYYARV_MAX_ARGC];
    struct funcallv_args a;
    int i;

    if (argc < 0 || argc > RPYYARV_MAX_ARGC) {
        *state = -1;
        return (uintptr_t)Qnil;
    }
    for (i = 0; i < argc; i++) buf[i] = (VALUE)argv[i];

    a.recv = (VALUE)recv;
    a.mid  = (ID)mid;
    a.argc = argc;
    a.argv = buf;

    *state = 0;
    VALUE r = rb_protect(funcallv_body, (VALUE)&a, state);
    absorb_unwind(state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
funcallv_public_body(VALUE argp)
{
    struct funcallv_args *a = (struct funcallv_args *)argp;
    return rb_funcallv_public(a->recv, a->mid, a->argc, a->argv);
}

/* rb_funcallv is CALL_FCALL and reaches a private method; a send with an explicit receiver must be refused one, since a toplevel def leaves a private trampoline on Object. */
uintptr_t
rpyyarv_funcallv_public_id(uintptr_t recv, uintptr_t mid, int argc,
                           const uintptr_t *argv, int *state)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    struct funcallv_args a;
    int i;

    if (argc < 0 || argc > RPYYARV_MAX_ARGC) {
        *state = -1;
        return (uintptr_t)Qnil;
    }
    for (i = 0; i < argc; i++) buf[i] = (VALUE)argv[i];

    a.recv = (VALUE)recv;
    a.mid  = (ID)mid;
    a.argc = argc;
    a.argv = buf;

    *state = 0;
    VALUE r = rb_protect(funcallv_public_body, (VALUE)&a, state);
    absorb_unwind(state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
funcallv_kw_body(VALUE argp)
{
    struct funcallv_args *a = (struct funcallv_args *)argp;
    if (a->pub)
        return rb_funcallv_public_kw(a->recv, a->mid, a->argc, a->argv,
                                     RB_PASS_KEYWORDS);
    return rb_funcallv_kw(a->recv, a->mid, a->argc, a->argv, RB_PASS_KEYWORDS);
}

/* The last argument is a Hash of keywords; RB_PASS_KEYWORDS is what tells the callee to unpack it rather than take it as a positional. */
uintptr_t
rpyyarv_funcallv_kw_id(uintptr_t recv, uintptr_t mid, int argc,
                       const uintptr_t *argv, int pub, int *state)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    struct funcallv_args a;
    int i;

    if (argc < 1 || argc > RPYYARV_MAX_ARGC) {
        *state = -1;
        return (uintptr_t)Qnil;
    }
    for (i = 0; i < argc; i++) buf[i] = (VALUE)argv[i];

    a.recv = (VALUE)recv;
    a.mid  = (ID)mid;
    a.argc = argc;
    a.argv = buf;
    a.pub  = pub;

    *state = 0;
    VALUE r = rb_protect(funcallv_kw_body, (VALUE)&a, state);
    absorb_unwind(state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

uintptr_t
rpyyarv_funcallv(uintptr_t recv, const char *mid, int argc,
                 const uintptr_t *argv, int *state)
{
    return rpyyarv_funcallv_id(recv, (uintptr_t)rb_intern(mid), argc, argv,
                               state);
}

uintptr_t
rpyyarv_top_self(void)
{
    static VALUE top_self = Qundef;
    if (top_self == Qundef) {
        int state = 0;
        VALUE v = rb_eval_string_protect("self", &state);
        if (state) {
            rb_set_errinfo(Qnil);
            return (uintptr_t)Qnil;
        }
        rb_gc_register_mark_object(v);
        top_self = v;
    }
    return (uintptr_t)top_self;
}

uintptr_t
rpyyarv_int2inum(long n)
{
    return (uintptr_t)rb_int2inum(n);
}

/* Only for a double no flonum can hold: value.py encodes the rest itself. */
uintptr_t
rpyyarv_float_new(double d)
{
    return (uintptr_t)rb_float_new(d);
}

void
rpyyarv_float_layout(int *out)
{
    out[0] = (int)(offsetof(struct RFloat, float_value) / SIZEOF_VALUE);
    out[1] = (int)USE_FLONUM;
    out[2] = (int)(SIZEOF_DOUBLE <= SIZEOF_VALUE);
}

void
rpyyarv_special_consts(uintptr_t *qfalse, uintptr_t *qnil, uintptr_t *qtrue,
                       uintptr_t *fixnum_flag)
{
    *qfalse = (uintptr_t)RUBY_Qfalse;
    *qnil = (uintptr_t)RUBY_Qnil;
    *qtrue = (uintptr_t)RUBY_Qtrue;
    *fixnum_flag = (uintptr_t)RUBY_FIXNUM_FLAG;
}

uintptr_t
rpyyarv_iseqw_new(void *iseq)
{
    VALUE v = rb_iseqw_new((const struct rb_iseq_struct *)iseq);
    /* Held only in FFI-side memory the GC never scans; pinning it also marks the wrapped iseq, and this runs once at boot. */
    rb_gc_register_mark_object(v);
    return (uintptr_t)v;
}

long
rpyyarv_str_len(uintptr_t str)
{
    VALUE v = (VALUE)str;
    if (!RB_TYPE_P(v, T_STRING)) return -1;
    return RSTRING_LEN(v);
}

const char *
rpyyarv_str_ptr(uintptr_t str)
{
    return RSTRING_PTR((VALUE)str);
}

struct inspect_args {
    VALUE obj;
    VALUE out;
};

static VALUE
inspect_body(VALUE argp)
{
    struct inspect_args *a = (struct inspect_args *)argp;
    a->out = rb_inspect(a->obj);
    return a->out;
}

const char *
rpyyarv_inspect_cstr(uintptr_t obj)
{
    struct inspect_args a;
    a.obj = (VALUE)obj;
    a.out = Qnil;

    int state = 0;
    rb_protect(inspect_body, (VALUE)&a, &state);
    if (state) {
        rb_set_errinfo(Qnil);
        return NULL;
    }
    return rb_string_value_cstr(&a.out);
}

long
rpyyarv_ary_len(uintptr_t ary)
{
    VALUE v = (VALUE)ary;
    if (!RB_TYPE_P(v, T_ARRAY)) return -1;
    return RARRAY_LEN(v);
}

uintptr_t
rpyyarv_ary_entry(uintptr_t ary, long idx)
{
    return (uintptr_t)rb_ary_entry((VALUE)ary, idx);
}

uintptr_t
rpyyarv_ary_subseq(uintptr_t ary, long beg, long len)
{
    return (uintptr_t)rb_ary_subseq((VALUE)ary, beg, len);
}

int rpyyarv_is_array(uintptr_t v)  { return RB_TYPE_P((VALUE)v, T_ARRAY) ? 1 : 0; }
int rpyyarv_is_symbol(uintptr_t v) { return SYMBOL_P((VALUE)v) ? 1 : 0; }
int rpyyarv_is_fixnum(uintptr_t v) { return FIXNUM_P((VALUE)v) ? 1 : 0; }
int rpyyarv_is_string(uintptr_t v) { return RB_TYPE_P((VALUE)v, T_STRING) ? 1 : 0; }
int rpyyarv_is_hash(uintptr_t v)   { return RB_TYPE_P((VALUE)v, T_HASH) ? 1 : 0; }
int rpyyarv_is_nil(uintptr_t v)    { return NIL_P((VALUE)v) ? 1 : 0; }
int rpyyarv_is_true(uintptr_t v)   { return (VALUE)v == Qtrue ? 1 : 0; }
int rpyyarv_is_false(uintptr_t v)  { return (VALUE)v == Qfalse ? 1 : 0; }

static ID id_method_original_name;
static ID id_method_original_eq;
static ID id_method_original_eql;
static ID id_method_original_hash;

static VALUE
rpyyarv_method_eq(VALUE self, VALUE other)
{
    VALUE klass = rb_path2class("Method");
    if (rb_obj_class(other) != klass) return Qfalse;
    if (rb_funcall(self, id_method_original_name, 0) !=
        rb_funcall(other, id_method_original_name, 0)) return Qfalse;
    return rb_funcall(self, id_method_original_eq, 1, other);
}

static VALUE
rpyyarv_method_eql(VALUE self, VALUE other)
{
    VALUE klass = rb_path2class("Method");
    if (rb_obj_class(other) != klass) return Qfalse;
    if (rb_funcall(self, id_method_original_name, 0) !=
        rb_funcall(other, id_method_original_name, 0)) return Qfalse;
    return rb_funcall(self, id_method_original_eql, 1, other);
}

static VALUE
rpyyarv_method_hash(VALUE self)
{
    VALUE parts[2];
    parts[0] = rb_funcall(self, id_method_original_hash, 0);
    parts[1] = rb_funcall(self, id_method_original_name, 0);
    return rb_funcall(rb_ary_new_from_values(2, parts), rb_intern("hash"), 0);
}

void
rpyyarv_patch_method_equality(void)
{
    VALUE klass = rb_path2class("Method");
    id_method_original_name = rb_intern("original_name");
    id_method_original_eq = rb_intern("__rpyyarv_original_equal__");
    id_method_original_eql = rb_intern("__rpyyarv_original_eql__");
    id_method_original_hash = rb_intern("__rpyyarv_original_hash__");
    rb_alias(klass, id_method_original_eq, rb_intern("=="));
    rb_alias(klass, id_method_original_eql, rb_intern("eql?"));
    rb_alias(klass, id_method_original_hash, rb_intern("hash"));
    rb_define_method(klass, "==", rpyyarv_method_eq, 1);
    rb_define_method(klass, "eql?", rpyyarv_method_eql, 1);
    rb_define_method(klass, "hash", rpyyarv_method_hash, 0);
}

long
rpyyarv_num2long(uintptr_t v)
{
    VALUE val = (VALUE)v;
    if (!RB_INTEGER_TYPE_P(val)) return 0;
    return NUM2LONG(val);
}

uintptr_t
rpyyarv_hash_aref(uintptr_t hash, const char *key)
{
    VALUE h = (VALUE)hash;
    if (!RB_TYPE_P(h, T_HASH)) return (uintptr_t)Qnil;
    return (uintptr_t)rb_hash_aref(h, ID2SYM(rb_intern(key)));
}

const char *
rpyyarv_sym_cstr(uintptr_t sym)
{
    VALUE v = (VALUE)sym;
    if (!SYMBOL_P(v)) return NULL;
    return rb_id2name(SYM2ID(v));
}

static void (*gc_mark_hook)(void);

/* dmark runs with the data pointer; the hook itself needs no state. */
static void
gc_hook_dmark(void *unused)
{
    (void)unused;
    if (gc_mark_hook) gc_mark_hook();
}

static size_t
gc_hook_dsize(const void *unused)
{
    (void)unused;
    return 0;
}

static const rb_data_type_t gc_hook_type = {
    "rpyyarv/gc_mark_hook",
    { gc_hook_dmark, NULL, gc_hook_dsize, NULL, { NULL } },
    0, 0, 0,
};

/* T_DATA with a NULL data pointer never has its dmark called. */
static int gc_hook_payload;
static VALUE gc_hook_obj = Qnil;

void
rpyyarv_gc_set_mark_hook(void (*fn)(void))
{
    gc_mark_hook = fn;
    if (fn == NULL) return;
    if (!NIL_P(gc_hook_obj)) return;

    gc_hook_obj = TypedData_Wrap_Struct(0, &gc_hook_type, &gc_hook_payload);
    rb_gc_register_address(&gc_hook_obj);
}

void
rpyyarv_gc_mark_value(uintptr_t v)
{
    rb_gc_mark((VALUE)v);
}

void
rpyyarv_gc_mark_maybe(uintptr_t v)
{
    rb_gc_mark_maybe((VALUE)v);
}

static void (*const_hook)(void);

static void
const_changed(ID id)
{
    (void)id;
    if (const_hook) const_hook();
}

void
rpyyarv_set_const_hook(void (*fn)(void))
{
    const_hook = fn;
    rb_rpyyarv_set_constant_hook(fn ? const_changed : NULL);
}

void
rpyyarv_set_method_hook(void (*fn)(void))
{
    rb_rpyyarv_set_method_hook(fn);
}

void
rpyyarv_gc_start(void)
{
    rb_gc_start();
}

uintptr_t
rpyyarv_str_new(const char *s, long n)
{
    return (uintptr_t)rb_str_new(s, n);
}

uintptr_t
rpyyarv_ary_new(int n, const uintptr_t *elems)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    int i;
    if (n < 0 || n > RPYYARV_MAX_ARGC) return (uintptr_t)Qundef;
    for (i = 0; i < n; i++) buf[i] = (VALUE)elems[i];
    return (uintptr_t)rb_ary_new_from_values(n, buf);
}

void
rpyyarv_core_classes(uintptr_t *out)
{
    out[0]  = (uintptr_t)rb_cObject;
    out[1]  = (uintptr_t)rb_cInteger;
    out[2]  = (uintptr_t)rb_cFloat;
    out[3]  = (uintptr_t)rb_cSymbol;
    out[4]  = (uintptr_t)rb_cNilClass;
    out[5]  = (uintptr_t)rb_cTrueClass;
    out[6]  = (uintptr_t)rb_cFalseClass;
    out[7]  = (uintptr_t)rb_cString;
    out[8]  = (uintptr_t)rb_cArray;
    out[9]  = (uintptr_t)rb_cHash;
    out[10] = (uintptr_t)rb_cClass;
    out[11] = (uintptr_t)rb_cModule;
    out[12] = (uintptr_t)rb_cBasicObject;
    out[13] = (uintptr_t)rb_mMath;
}

struct owner_args {
    VALUE klass;
    ID    id;
};

static VALUE
method_owner_body(VALUE argp)
{
    struct owner_args *p = (struct owner_args *)argp;
    VALUE m = rb_funcall(p->klass, rb_intern("instance_method"), 1,
                         ID2SYM(p->id));
    return rb_funcall(m, rb_intern("owner"), 0);
}

uintptr_t
rpyyarv_method_owner(uintptr_t klass, uintptr_t id)
{
    struct owner_args a;
    int state = 0;
    VALUE r;
    a.klass = (VALUE)klass;
    a.id = (ID)id;
    r = rb_protect(method_owner_body, (VALUE)&a, &state);
    /* No such method, or klass is not a Module: not an error here. */
    if (state) {
        rb_set_errinfo(Qnil);
        return (uintptr_t)Qnil;
    }
    return (uintptr_t)r;
}

struct super_args {
    VALUE klass;
    VALUE owner;
    ID    id;
};

static VALUE
super_owner_body(VALUE argp)
{
    struct super_args *p = (struct super_args *)argp;
    ID owner_id = rb_intern("owner");
    ID super_id = rb_intern("super_method");
    /* UnboundMethod#super_method carries the iclass it was found through, so a prepended or included module counts. */
    VALUE m = rb_funcall(p->klass, rb_intern("instance_method"), 1,
                         ID2SYM(p->id));
    while (!NIL_P(m)) {
        VALUE found = rb_funcall(m, owner_id, 0);
        m = rb_funcall(m, super_id, 0);
        if (found == p->owner) {
            if (NIL_P(m)) return Qnil;
            return rb_funcall(m, owner_id, 0);
        }
    }
    return Qnil;
}

uintptr_t
rpyyarv_super_owner(uintptr_t klass, uintptr_t owner, uintptr_t id)
{
    struct super_args a;
    int state = 0;
    VALUE r;
    a.klass = (VALUE)klass;
    a.owner = (VALUE)owner;
    a.id = (ID)id;
    r = rb_protect(super_owner_body, (VALUE)&a, &state);
    if (state) {
        rb_set_errinfo(Qnil);
        return (uintptr_t)Qnil;
    }
    return (uintptr_t)r;
}

static VALUE
responds_body(VALUE argp)
{
    struct owner_args *p = (struct owner_args *)argp;
    /* respond_to? excludes protected as well as private (rb_method_boundp with BOUND_RESPONDS). */
    return rb_funcall(p->klass, rb_intern("public_method_defined?"), 1,
                      ID2SYM(p->id));
}

struct super_call_args {
    VALUE klass;
    VALUE owner;
    VALUE recv;
    ID    id;
    int   argc;
    const VALUE *argv;
    /* RB_PASS_KEYWORDS when the last argument is the keyword Hash. */
    int   kw_splat;
    VALUE proc;
};

static VALUE
call_super_body(VALUE argp)
{
    struct super_call_args *p = (struct super_call_args *)argp;
    VALUE args[RPYYARV_MAX_ARGC + 1];
    int i;
    ID owner_id = rb_intern("owner");
    ID super_id = rb_intern("super_method");
    /* The method after the running one along the receiver's own chain, which is
       the only walk that sees a prepended module; instance_method(owner) would
       resolve back to the prepended copy and recurse forever. */
    VALUE m = rb_funcall(p->klass, rb_intern("instance_method"), 1,
                         ID2SYM(p->id));
    while (!NIL_P(m)) {
        VALUE found = rb_funcall(m, owner_id, 0);
        m = rb_funcall(m, super_id, 0);
        if (found == p->owner) break;
    }
    if (NIL_P(m)) return Qundef;
    /* UnboundMethod#bind_call, not rb_call_super: super needs a CRuby control frame, binding one method does not. */
    args[0] = p->recv;
    for (i = 0; i < p->argc; i++) args[i + 1] = p->argv[i];
    /* With the block, since a bare `super` forwards the one its method was given (vm_insnhelper.c:5033); Qnil means none. */
    return rb_funcall_with_block_kw(m, rb_intern("bind_call"), p->argc + 1,
                                    args, p->proc, p->kw_splat);
}

uintptr_t
rpyyarv_call_super(uintptr_t klass, uintptr_t owner, uintptr_t recv,
                   uintptr_t id, int argc, const uintptr_t *argv, int kw,
                   uintptr_t proc, int *state)
{
    struct super_call_args a;
    VALUE local[RPYYARV_MAX_ARGC];
    int i;
    if (argc > RPYYARV_MAX_ARGC) {
        *state = -1;
        return (uintptr_t)Qnil;
    }
    /* argv may live in memory CRuby never scans, so it is copied to the machine stack first, as funcallv does. */
    for (i = 0; i < argc; i++) local[i] = (VALUE)argv[i];
    a.klass = (VALUE)klass;
    a.owner = (VALUE)owner;
    a.recv = (VALUE)recv;
    a.id = (ID)id;
    a.argc = argc;
    a.argv = local;
    a.kw_splat = kw ? RB_PASS_KEYWORDS : RB_NO_KEYWORDS;
    a.proc = proc ? (VALUE)proc : Qnil;
    *state = 0;
    return (uintptr_t)rb_protect(call_super_body, (VALUE)&a, state);
}

static VALUE
dir_of_body(VALUE argp)
{
    VALUE path = *(VALUE *)argp;
    /* __dir__ is dirname(realpath(the running file)) (vm_eval.c's f_dir). */
    VALUE real = rb_funcall(rb_cFile, rb_intern("realpath"), 1, path);
    return rb_funcall(rb_cFile, rb_intern("dirname"), 1, real);
}

struct cvar_args {
    VALUE klass;
    VALUE val;
    ID    id;
};

static VALUE
cvar_get_body(VALUE argp)
{
    struct cvar_args *p = (struct cvar_args *)argp;
    return rb_cvar_get(p->klass, p->id);
}

static VALUE
cvar_set_body(VALUE argp)
{
    struct cvar_args *p = (struct cvar_args *)argp;
    rb_cvar_set(p->klass, p->id, p->val);
    return Qnil;
}

uintptr_t
rpyyarv_cvar_get(uintptr_t klass, uintptr_t id, int *state)
{
    struct cvar_args a;
    a.klass = (VALUE)klass;
    a.id = (ID)id;
    a.val = Qnil;
    *state = 0;
    return (uintptr_t)rb_protect(cvar_get_body, (VALUE)&a, state);
}

void
rpyyarv_cvar_set(uintptr_t klass, uintptr_t id, uintptr_t val, int *state)
{
    struct cvar_args a;
    a.klass = (VALUE)klass;
    a.id = (ID)id;
    a.val = (VALUE)val;
    *state = 0;
    rb_protect(cvar_set_body, (VALUE)&a, state);
}

int
rpyyarv_cvar_defined(uintptr_t klass, uintptr_t id)
{
    return rb_cvar_defined((VALUE)klass, (ID)id) ? 1 : 0;
}

/* A `class << self` scope names no class variables of its own (vm_get_cvar_base). */
int
rpyyarv_is_singleton_class(uintptr_t klass)
{
    VALUE k = (VALUE)klass;
    if (SPECIAL_CONST_P(k) || !RB_TYPE_P(k, T_CLASS)) return 0;
    return RTEST(rb_funcall(k, rb_intern("singleton_class?"), 0)) ? 1 : 0;
}

uintptr_t
rpyyarv_dir_of(uintptr_t path)
{
    VALUE p = (VALUE)path;
    int state = 0;
    VALUE r = rb_protect(dir_of_body, (VALUE)&p, &state);
    if (state) {
        rb_set_errinfo(Qnil);
        return (uintptr_t)Qundef;
    }
    return (uintptr_t)r;
}

uintptr_t
rpyyarv_current_receiver(void)
{
    return (uintptr_t)rb_current_receiver();
}

uintptr_t
rpyyarv_sym_name(uintptr_t sym)
{
    if (!RB_STATIC_SYM_P((VALUE)sym)) return (uintptr_t)Qundef;
    /* rb_sym2str is the symbol's own frozen name; Symbol#name returns exactly this object. */
    return (uintptr_t)rb_sym2str((VALUE)sym);
}

int
rpyyarv_responds(uintptr_t klass, uintptr_t sym)
{
    struct owner_args a;
    int state = 0;
    VALUE r;
    if (!RB_STATIC_SYM_P((VALUE)sym)) return -1;
    a.klass = (VALUE)klass;
    a.id = SYM2ID((VALUE)sym);
    /* An overridden respond_to? or respond_to_missing? can answer per receiver, so no per-class answer exists. */
    if (!rb_method_basic_definition_p(a.klass, rb_intern("respond_to?")) ||
        !rb_method_basic_definition_p(a.klass, rb_intern("respond_to_missing?")))
        return -1;
    r = rb_protect(responds_body, (VALUE)&a, &state);
    if (state) {
        rb_set_errinfo(Qnil);
        return -1;
    }
    return RTEST(r) ? 1 : 0;
}

static VALUE
ary_to_ary_body(VALUE obj)
{
    return rb_ary_to_ary(obj);
}

/* vm_expandarray's conversion: to_ary when the object has one, else a one-element Array. */
uintptr_t
rpyyarv_ary_to_ary(uintptr_t obj, int *state)
{
    *state = 0;
    return (uintptr_t)rb_protect(ary_to_ary_body, (VALUE)obj, state);
}

struct obj_args {
    VALUE a;
    VALUE b;
    VALUE c;
    ID    id;
};

static VALUE
define_class_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_define_class_id_under(p->a, p->id, p->b);
}

uintptr_t
rpyyarv_define_class(uintptr_t cbase, uintptr_t id, uintptr_t super,
                     int *state)
{
    struct obj_args a;
    a.a = (VALUE)cbase;
    a.b = (VALUE)super;
    a.id = (ID)id;
    *state = 0;
    VALUE r = rb_protect(define_class_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* rb_define_module_id_under reopens an existing module itself, so no separate lookup. */
static VALUE
define_module_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_define_module_id_under(p->a, p->id);
}

uintptr_t
rpyyarv_define_module(uintptr_t cbase, uintptr_t id, int *state)
{
    struct obj_args a;
    a.a = (VALUE)cbase;
    a.id = (ID)id;
    *state = 0;
    VALUE r = rb_protect(define_module_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
class_superclass_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_class_superclass(p->a);
}

uintptr_t
rpyyarv_class_superclass(uintptr_t klass, int *state)
{
    struct obj_args a;
    a.a = (VALUE)klass;
    *state = 0;
    VALUE r = rb_protect(class_superclass_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
singleton_class_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    /* Checks the receiver may have one and is not frozen (vm_insnhelper.c:6035). */
    return rb_singleton_class(p->a);
}

uintptr_t
rpyyarv_singleton_class(uintptr_t obj, int *state)
{
    struct obj_args a;
    a.a = (VALUE)obj;
    *state = 0;
    VALUE r = rb_protect(singleton_class_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
obj_alloc_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_obj_alloc(p->a);
}

uintptr_t
rpyyarv_obj_alloc(uintptr_t klass, int *state)
{
    struct obj_args a;
    a.a = (VALUE)klass;
    *state = 0;
    VALUE r = rb_protect(obj_alloc_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* No rb_protect: dispatch.py only allocates classes it defined itself, which always kept Object's allocator. */
uintptr_t
rpyyarv_obj_alloc_fast(uintptr_t klass)
{
    return (uintptr_t)rb_obj_alloc((VALUE)klass);
}

static VALUE
const_get_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_const_get(p->a, p->id);
}

uintptr_t
rpyyarv_const_get(uintptr_t klass, uintptr_t id, int *state)
{
    struct obj_args a;
    a.a = (VALUE)klass;
    a.id = (ID)id;
    *state = 0;
    VALUE r = rb_protect(const_get_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
const_at_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    /* rb_const_lookup, which vm_get_ev_const walks the cref chain with: this class's own table, no ancestors and no Object fallback. */
    if (!rb_const_defined_at(p->a, p->id)) return Qundef;
    return rb_const_get_at(p->a, p->id);
}

uintptr_t
rpyyarv_const_at(uintptr_t klass, uintptr_t id, int *state)
{
    struct obj_args a;
    a.a = (VALUE)klass;
    a.id = (ID)id;
    *state = 0;
    VALUE r = rb_protect(const_at_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
const_set_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    rb_const_set(p->a, p->id, p->b);
    return Qnil;
}

void
rpyyarv_const_set(uintptr_t klass, uintptr_t id, uintptr_t val, int *state)
{
    struct obj_args a;
    a.a = (VALUE)klass;
    a.b = (VALUE)val;
    a.id = (ID)id;
    *state = 0;
    rb_protect(const_set_body, (VALUE)&a, state);
}

static VALUE
ivar_get_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_ivar_get(p->a, p->id);
}

uintptr_t
rpyyarv_ivar_get(uintptr_t obj, uintptr_t id, int *state)
{
    struct obj_args a;
    a.a = (VALUE)obj;
    a.id = (ID)id;
    *state = 0;
    VALUE r = rb_protect(ivar_get_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
ivar_set_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    rb_ivar_set(p->a, p->id, p->b);
    return Qnil;
}

void
rpyyarv_ivar_set(uintptr_t obj, uintptr_t id, uintptr_t val, int *state)
{
    struct obj_args a;
    a.a = (VALUE)obj;
    a.b = (VALUE)val;
    a.id = (ID)id;
    *state = 0;
    rb_protect(ivar_set_body, (VALUE)&a, state);
}

/* A corrupt shape tree would otherwise spin here forever. */
#define RPYYARV_SHAPE_MAX_DEPTH 256

int
rpyyarv_shape_iv_index(unsigned int shape_id, uintptr_t id, int *index)
{
    *index = -1;
    if (shape_id == INVALID_SHAPE_ID) return -1;
    /* A too-complex object keeps its ivars in an st_table, not in slots. */
    if (rb_shape_too_complex_p((shape_id_t)shape_id)) return -1;

    rb_shape_t *shape = RSHAPE((shape_id_t)shape_id);
    int depth = 0;
    while (shape->parent_id != INVALID_SHAPE_ID) {
        if (++depth > RPYYARV_SHAPE_MAX_DEPTH) return -1;
        if (shape->type == SHAPE_IVAR && shape->edge_name == (ID)id) {
            if (shape->next_field_index == 0) return -1;
            *index = (int)(shape->next_field_index - 1);
            return 1;
        }
        shape = RSHAPE(shape->parent_id);
    }
    return 0;
}

/* RB_OBJ_WRITE's barrier half for a raw ivar store: gc/default/default.c:6085 only sets remembered/marking bits and raw-mallocs a mark-stack chunk, allocating no Ruby object and running no mark callback, so boot.py may declare it without random_effects_on_gcobjs. */
void
rpyyarv_obj_written(uintptr_t a, uintptr_t b)
{
    RB_OBJ_WRITTEN((VALUE)a, Qundef, (VALUE)b);
}

/* False when rb_gc_writebarrier is a modular-GC function pointer instead of the barrier above, which this shim cannot make the same promise about. */
int
rpyyarv_wb_direct(void)
{
#if USE_MODULAR_GC
    return 0;
#else
    return 1;
#endif
}

void
rpyyarv_object_layout(int *out)
{
    out[0] = (int)SHAPE_FLAG_SHIFT;
    out[1] = (int)SHAPE_ID_NUM_BITS;
    out[2] = (int)ROBJECT_HEAP;
    out[3] = (int)(offsetof(struct RObject, as.ary) / SIZEOF_VALUE);
    out[4] = (int)RUBY_T_MASK;
    out[5] = (int)RUBY_T_OBJECT;
    out[6] = (int)RUBY_FL_FREEZE;
    /* Nonzero would put the shape id in its own word, not in the flags the RPython side reads and writes. */
    out[7] = (int)RBASIC_SHAPE_ID_FIELD;
    out[8] = (int)RUBY_T_DATA;
    out[9] = (int)RUBY_TYPED_FL_IS_TYPED_DATA;
    /* Where a typed T_DATA keeps its imemo/fields; RData puts a function pointer here, hence the flag above. */
    out[10] = (int)(offsetof(struct RTypedData, fields_obj) / SIZEOF_VALUE);
    /* Set on the objects ivar_ractor_check (variable.c:1220) may raise for. */
    out[11] = (int)RUBY_FL_SHAREABLE;
}

/* Neither allocates nor raises, so boot.py may declare it without reenters. */
int
rpyyarv_shape_add_ivar_fits(unsigned int before, unsigned int after,
                            uintptr_t id, int *index)
{
    *index = -1;
    if (before == INVALID_SHAPE_ID || after == INVALID_SHAPE_ID) return 0;
    if (rb_shape_too_complex_p((shape_id_t)before)) return 0;
    if (rb_shape_too_complex_p((shape_id_t)after)) return 0;
    /* Same flags and same parent, so the shape id write changes nothing but the offset. */
    if (!RSHAPE_DIRECT_CHILD_P((shape_id_t)before, (shape_id_t)after)) return 0;

    rb_shape_t *shape = RSHAPE((shape_id_t)after);
    if (shape->type != SHAPE_IVAR || shape->edge_name != (ID)id) return 0;
    /* One field more than before, so the slot is the first unused one and no field is left uninitialized for the GC to scan. */
    if (shape->next_field_index != RSHAPE_LEN((shape_id_t)before) + 1) return 0;

    attr_index_t slot = shape->next_field_index - 1;
    /* The condition obj_field_set reallocates the fields on (variable.c:1957), which a raw store cannot do. */
    if (slot >= RSHAPE_CAPACITY((shape_id_t)before)) return 0;

    *index = (int)slot;
    return 1;
}

void
rpyyarv_array_layout(int *out)
{
    out[0] = (int)RARRAY_EMBED_FLAG;
    out[1] = (int)RARRAY_EMBED_LEN_SHIFT;
    out[2] = (int)RARRAY_EMBED_LEN_MASK;
    out[3] = (int)(offsetof(struct RArray, as.heap.len) / SIZEOF_VALUE);
    out[4] = (int)(offsetof(struct RArray, as.heap.ptr) / SIZEOF_VALUE);
    out[5] = (int)(offsetof(struct RArray, as.ary) / SIZEOF_VALUE);
    out[6] = (int)RARRAY_SHARED_FLAG;
    out[7] = (int)RARRAY_SHARED_ROOT_FLAG;
    out[8] = (int)(offsetof(struct RArray, as.heap.aux.capa) / SIZEOF_VALUE);
    out[9] = (int)T_ARRAY;
}

/* vm_opt_str_eq's arm (vm_insnhelper.c:2540); Qundef when the argument is no String, which helpers.py answers for. No rb_protect: rb_str_eql_internal neither allocates nor raises. */
uintptr_t
rpyyarv_str_eq(uintptr_t a, uintptr_t b)
{
    VALUE x = (VALUE)a, y = (VALUE)b;
    if (x == y) return (uintptr_t)Qtrue;
    if (!RB_TYPE_P(y, T_STRING)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_str_eql_internal(x, y);
}

static VALUE
ary_resurrect_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_ary_resurrect(p->a);
}

uintptr_t
rpyyarv_ary_resurrect(uintptr_t ary, int *state)
{
    struct obj_args a;
    a.a = (VALUE)ary;
    *state = 0;
    VALUE r = rb_protect(ary_resurrect_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

struct ary_store_args {
    VALUE ary;
    VALUE val;
    long  idx;
};

static VALUE
ary_store_body(VALUE argp)
{
    struct ary_store_args *p = (struct ary_store_args *)argp;
    rb_ary_store(p->ary, p->idx, p->val);
    return Qnil;
}

void
rpyyarv_ary_store(uintptr_t ary, long idx, uintptr_t val, int *state)
{
    struct ary_store_args a;
    a.ary = (VALUE)ary;
    a.val = (VALUE)val;
    a.idx = idx;
    *state = 0;
    rb_protect(ary_store_body, (VALUE)&a, state);
}

static VALUE
ary_new_capa_body(VALUE argp)
{
    struct ary_store_args *p = (struct ary_store_args *)argp;
    return rb_ary_new_capa(p->idx);
}

uintptr_t
rpyyarv_ary_new_capa(long capa, int *state)
{
    struct ary_store_args a;
    a.idx = capa;
    *state = 0;
    VALUE r = rb_protect(ary_new_capa_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* No rb_protect: interp.py checks 0 <= capa, and the only other raise here is NoMemoryError. */
uintptr_t
rpyyarv_ary_new_capa_fast(long capa)
{
    return (uintptr_t)rb_ary_new_capa(capa);
}

/* No rb_protect: the array is one _array_new_block just made, so it is neither frozen nor shared, and 0 <= idx < its capacity. */
void
rpyyarv_ary_store_fresh(uintptr_t ary, long idx, uintptr_t val)
{
    rb_ary_store((VALUE)ary, idx, (VALUE)val);
}

/* rb_ary_initialize's non-block half (array.c:1194): every element is the same VALUE, not a copy. */
static VALUE
ary_new_filled_body(VALUE argp)
{
    struct ary_store_args *p = (struct ary_store_args *)argp;
    VALUE ary = rb_ary_resize(rb_ary_new_capa(p->idx), p->idx);
    if (p->val != Qnil) {
        /* ary_memfill: one barrier covers n copies of the same VALUE. */
        RARRAY_PTR_USE(ary, ptr, {
            for (long i = 0; i < p->idx; i++) ptr[i] = p->val;
            RB_OBJ_WRITTEN(ary, Qundef, p->val);
        });
    }
    return ary;
}

uintptr_t
rpyyarv_ary_new_filled(long len, uintptr_t val, int *state)
{
    struct ary_store_args a;
    a.val = (VALUE)val;
    a.idx = len;
    *state = 0;
    VALUE r = rb_protect(ary_new_filled_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* No rb_protect: interp.py checks 0 <= len <= ARY_NEW_FILL_MAX, so nothing below raises but NoMemoryError. */
uintptr_t
rpyyarv_ary_new_filled_fast(long len, uintptr_t val)
{
    struct ary_store_args a;
    a.val = (VALUE)val;
    a.idx = len;
    return (uintptr_t)ary_new_filled_body((VALUE)&a);
}

struct ary_cat_args {
    VALUE ary;
    const VALUE *elems;
    long n;
};

static VALUE
ary_cat_body(VALUE argp)
{
    struct ary_cat_args *p = (struct ary_cat_args *)argp;
    return rb_ary_cat(p->ary, p->elems, p->n);
}

void
rpyyarv_ary_cat(uintptr_t ary, int n, const uintptr_t *elems, int *state)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    struct ary_cat_args a;
    int i;

    if (n < 0 || n > RPYYARV_MAX_ARGC) { *state = -1; return; }
    for (i = 0; i < n; i++) buf[i] = (VALUE)elems[i];

    a.ary = (VALUE)ary;
    a.elems = buf;
    a.n = n;
    *state = 0;
    rb_protect(ary_cat_body, (VALUE)&a, state);
}

struct range_args {
    VALUE low;
    VALUE high;
    int   excl;
};

static VALUE
range_new_body(VALUE argp)
{
    struct range_args *p = (struct range_args *)argp;
    return rb_range_new(p->low, p->high, p->excl);
}

uintptr_t
rpyyarv_range_new(uintptr_t low, uintptr_t high, int excl, int *state)
{
    struct range_args a;
    a.low = (VALUE)low;
    a.high = (VALUE)high;
    a.excl = excl;
    *state = 0;
    VALUE r = rb_protect(range_new_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

struct gvar_args {
    const char *name;
    VALUE val;
};

static VALUE
gvar_get_body(VALUE argp)
{
    struct gvar_args *p = (struct gvar_args *)argp;
    return rb_gv_get(p->name);
}

uintptr_t
rpyyarv_gvar_get(const char *name, int *state)
{
    struct gvar_args a;
    a.name = name;
    *state = 0;
    VALUE r = rb_protect(gvar_get_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
gvar_set_body(VALUE argp)
{
    struct gvar_args *p = (struct gvar_args *)argp;
    return rb_gv_set(p->name, p->val);
}

void
rpyyarv_gvar_set(const char *name, uintptr_t val, int *state)
{
    struct gvar_args a;
    a.name = name;
    a.val = (VALUE)val;
    *state = 0;
    rb_protect(gvar_set_body, (VALUE)&a, state);
}

static rpyyarv_block_fn block_callback;

void
rpyyarv_set_block_callback(rpyyarv_block_fn fn)
{
    block_callback = fn;
}

/* A handle's owner: kept alive by the ifunc (imemo.c marks ifunc->data), so it dies only when nothing in CRuby can call the block any more; its dfree queues the handle for reuse instead of the eager release that broke stored blocks (Hash default_proc, Liquid callbacks). */
static long *dead_handles;
static int n_dead, cap_dead;

static void
handle_owner_dfree(void *p)
{
    if (n_dead == cap_dead) {
        int cap = cap_dead ? cap_dead * 2 : 64;
        long *grown = realloc(dead_handles, cap * sizeof(long));
        if (!grown) return; /* leak the slot rather than crash in sweep */
        dead_handles = grown;
        cap_dead = cap;
    }
    dead_handles[n_dead++] = (long)(uintptr_t)p - 1;
}

/* The shadowstack swap runs here rather than in RPython: entering RPython pushes a frame of its own, and the copy has to happen with none of ours on the stack. */
static rpyyarv_fiber_save_fn fiber_park_callback;
static rpyyarv_fiber_arrive_fn fiber_unpark_callback;
static void **fiber_ss_base;
static void **fiber_ss_top;

static void
fiber_park(long key)
{
    char *buf = fiber_park_callback(key);
    char *base = (char *)*fiber_ss_base;
    long len = (char *)*fiber_ss_top - base;
    if (!buf) rb_fatal("rpyyarv: out of memory saving a fiber's shadowstack");
    *(long *)buf = len;
    memcpy(buf + sizeof(long), base, (size_t)len);
    *fiber_ss_top = base;
}

static void
fiber_unpark(long key, long stack_base, long stack_size)
{
    char *buf = fiber_unpark_callback(key, stack_base, stack_size);
    char *base = (char *)*fiber_ss_base;
    long len;
    if (!buf) return;             /* a fiber that never parked: nothing saved */
    len = *(long *)buf;
    memcpy(base, buf + sizeof(long), (size_t)len);
    *fiber_ss_top = base + len;
    *(long *)buf = 0;             /* the copy is live again; trace nothing */
}

void
rpyyarv_set_fiber_hooks(rpyyarv_fiber_save_fn park, rpyyarv_fiber_arrive_fn unpark,
                        rpyyarv_fiber_born_fn born, rpyyarv_fiber_key_fn died,
                        void **base_slot, void **top_slot)
{
    static rb_rpyyarv_fiber_hooks_t hooks;
    fiber_park_callback = park;
    fiber_unpark_callback = unpark;
    fiber_ss_base = base_slot;
    fiber_ss_top = top_slot;
    hooks.park = fiber_park;
    hooks.unpark = fiber_unpark;
    hooks.born = born;
    hooks.died = died;
    rb_rpyyarv_set_fiber_hooks(&hooks);
}

static rpyyarv_handle_mark_fn handle_mark_callback;

void
rpyyarv_set_handle_mark_callback(rpyyarv_handle_mark_fn fn)
{
    handle_mark_callback = fn;
}

/* The owner traces its block's frames itself, so a Proc nobody holds dies together with everything only it kept alive. */
static void
handle_owner_dmark(void *p)
{
    if (handle_mark_callback)
        handle_mark_callback((long)(uintptr_t)p - 1);
}

static const rb_data_type_t handle_owner_type = {
    "rpyyarv/block_handle",
    { handle_owner_dmark, handle_owner_dfree, 0 },
    0, 0, RUBY_TYPED_FREE_IMMEDIATELY
};

long
rpyyarv_pop_dead_handle(void)
{
    return n_dead ? dead_handles[--n_dead] : -1;
}

static VALUE
block_yielder(RB_BLOCK_CALL_FUNC_ARGLIST(yielded, callback_arg))
{
    /* On the machine stack, so the yielded values stay scannable until the RPython side copies them into a frame the mark hook reaches. */
    VALUE buf[RPYYARV_MAX_ARGC];
    int i, n = argc;
    VALUE r, here;

    (void)yielded;
    (void)blockarg;
    if (!block_callback) return Qnil;
    if (n < 0) n = 0;
    if (n > RPYYARV_MAX_ARGC) n = RPYYARV_MAX_ARGC;
    for (i = 0; i < n; i++) buf[i] = argv[i];
    /* The self this yield runs under; RPyYARV holds the one the block was handed over with and compares. A Fixnum arg is a permanent handle (rpyyarv_proc_new); a TypedData one is GC-owned. */
    here = rb_current_receiver();
    r = (VALUE)block_callback(FIXNUM_P(callback_arg)
                              ? (long)FIX2LONG(callback_arg)
                              : (long)(uintptr_t)RTYPEDDATA_DATA(callback_arg) - 1,
                              n, (uintptr_t *)buf, (uintptr_t)here);
    /* The block left early and parked why; abort the CRuby method running it instead of letting it iterate on. */
    if (block_unwind) {
        block_unwind = 0;
        rb_raise(unwind_class(), "rpyyarv: non-local exit from a block");
    }
    return r;
}

struct blockcall_args {
    VALUE recv;
    ID    mid;
    int   argc;
    const VALUE *argv;
    long  handle;
    /* RB_PASS_KEYWORDS when the last argument is a keyword Hash. */
    int   kw_splat;
};

static VALUE
call_with_block_body(VALUE argp)
{
    struct blockcall_args *a = (struct blockcall_args *)argp;
    VALUE owner = TypedData_Wrap_Struct(0, &handle_owner_type,
                                        (void *)(uintptr_t)(a->handle + 1));
    return rb_block_call_kw(a->recv, a->mid, a->argc, a->argv, block_yielder,
                            owner, a->kw_splat);
}

struct proccall_args {
    VALUE recv;
    ID    mid;
    int   argc;
    const VALUE *argv;
    VALUE proc;
    int   kw_splat;
};

static VALUE
call_with_proc_body(VALUE argp)
{
    struct proccall_args *a = (struct proccall_args *)argp;
    return rb_funcall_with_block_kw(a->recv, a->mid, a->argc, a->argv,
                                    a->proc, a->kw_splat);
}

/* The Proc itself as the block, not an ifunc over it: module_eval yields with a cref only its own block sees, and a bounce back through RPyYARV would lose it. */
uintptr_t
rpyyarv_call_with_proc(uintptr_t recv, uintptr_t mid, int argc,
                       const uintptr_t *argv, uintptr_t proc, int kw,
                       int *state)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    struct proccall_args a;
    int i;

    if (argc < 0 || argc > RPYYARV_MAX_ARGC) {
        *state = -1;
        return (uintptr_t)Qnil;
    }
    for (i = 0; i < argc; i++) buf[i] = (VALUE)argv[i];

    a.recv = (VALUE)recv;
    a.mid = (ID)mid;
    a.argc = argc;
    a.argv = buf;
    a.proc = proc ? (VALUE)proc : Qnil;
    a.kw_splat = kw ? RB_PASS_KEYWORDS : RB_NO_KEYWORDS;

    *state = 0;
    VALUE r = rb_protect(call_with_proc_body, (VALUE)&a, state);
    absorb_unwind(state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

uintptr_t
rpyyarv_call_with_block(uintptr_t recv, uintptr_t mid, int argc,
                        const uintptr_t *argv, long handle, int kw, int *state)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    struct blockcall_args a;
    int i;

    if (argc < 0 || argc > RPYYARV_MAX_ARGC) {
        *state = -1;
        return (uintptr_t)Qnil;
    }
    for (i = 0; i < argc; i++) buf[i] = (VALUE)argv[i];

    a.recv = (VALUE)recv;
    a.mid = (ID)mid;
    a.argc = argc;
    a.argv = buf;
    a.handle = handle;
    a.kw_splat = kw ? RB_PASS_KEYWORDS : RB_NO_KEYWORDS;

    *state = 0;
    VALUE r = rb_protect(call_with_block_body, (VALUE)&a, state);
    absorb_unwind(state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static rpyyarv_tramp_fn tramp_callback;

void
rpyyarv_set_trampoline_callback(rpyyarv_tramp_fn fn)
{
    tramp_callback = fn;
}

static VALUE
rpyyarv_trampoline(int argc, VALUE *argv, VALUE self)
{
    /* argv points into CRuby's VM stack, which rb_execution_context_mark already covers for the extent of the call; no second root here. */
    ID mid = rb_frame_this_func();
    VALUE blockproc = rb_block_given_p() ? rb_block_proc() : Qnil;
    /* A cfunc taking -1 arguments is handed the keyword Hash as its last positional; only this says the caller meant it as keywords. */
    int kw = rb_keyword_given_p() ? 1 : 0;
    int status = RPYYARV_TRAMP_OK;
    VALUE err = Qnil;
    VALUE r;

    if (!tramp_callback) {
        rb_raise(rb_eRuntimeError, "rpyyarv: no trampoline callback");
    }
    r = (VALUE)tramp_callback((uintptr_t)self, (uintptr_t)mid, argc,
                              (uintptr_t *)argv, (uintptr_t)blockproc, kw,
                              &status, (uintptr_t *)&err);
    /* Raised here, not on the RPython side: unwinding an RPython exception through this C frame back into libruby is undefined. */
    if (status == RPYYARV_TRAMP_RAISE) rb_exc_raise(err);
    if (status == RPYYARV_TRAMP_UNWIND) {
        rb_raise(unwind_class(), "rpyyarv: non-local exit from a method");
    }
    if (status != RPYYARV_TRAMP_OK) {
        rb_exc_raise(rb_exc_new_str(rb_eNotImpError, err));
    }
    return r;
}

struct defmeth_args {
    VALUE klass;
    ID    mid;
    int   is_private;
};

static VALUE
define_method_body(VALUE argp)
{
    struct defmeth_args *p = (struct defmeth_args *)argp;
    rb_define_method_id(p->klass, p->mid,
                        RUBY_METHOD_FUNC(rpyyarv_trampoline), -1);
    if (p->is_private) {
        /* A toplevel def lands on Object as private, and no ID-taking rb_define_private_method exists. */
        rb_funcall(p->klass, rb_intern("private"), 1, ID2SYM(p->mid));
    }
    return Qnil;
}

void
rpyyarv_define_method(uintptr_t klass, uintptr_t mid, int is_private,
                      int *state)
{
    struct defmeth_args a;
    a.klass = (VALUE)klass;
    a.mid = (ID)mid;
    a.is_private = is_private;
    *state = 0;
    rb_protect(define_method_body, (VALUE)&a, state);
}

static VALUE
proc_new_body(VALUE handle)
{
    /* The ifunc marks its data (imemo.c), so the owner lives exactly as long as the Proc: its dmark walks the env, its dfree frees the handle. */
    VALUE owner = TypedData_Wrap_Struct(0, &handle_owner_type,
                                        (void *)(uintptr_t)(FIX2LONG(handle) + 1));
    return rb_proc_new(block_yielder, owner);
}

uintptr_t
rpyyarv_proc_new(long handle, int *state)
{
    *state = 0;
    VALUE r = rb_protect(proc_new_body, LONG2FIX(handle), state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

int
rpyyarv_is_proc(uintptr_t v)
{
    return rb_obj_is_proc((VALUE)v) == Qtrue ? 1 : 0;
}

int
rpyyarv_is_class(uintptr_t v)
{
    VALUE val = (VALUE)v;
    if (SPECIAL_CONST_P(val)) return 0;
    return (RB_TYPE_P(val, T_CLASS) || RB_TYPE_P(val, T_MODULE)) ? 1 : 0;
}

void
rpyyarv_gc_register_mark_object(uintptr_t v)
{
    if (SPECIAL_CONST_P((VALUE)v)) return;
    rb_gc_register_mark_object((VALUE)v);
}

uintptr_t
rpyyarv_take_errinfo(void)
{
    VALUE e = rb_errinfo();
    rb_set_errinfo(Qnil);
    return (uintptr_t)e;
}

uintptr_t
rpyyarv_swap_errinfo(uintptr_t v)
{
    VALUE prev = rb_errinfo();
    rb_set_errinfo((VALUE)v);
    return (uintptr_t)prev;
}

static VALUE
obj_is_kind_of_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_obj_is_kind_of(p->a, p->b);
}

int
rpyyarv_obj_is_kind_of(uintptr_t obj, uintptr_t klass, int *state)
{
    struct obj_args a;
    a.a = (VALUE)obj;
    a.b = (VALUE)klass;
    *state = 0;
    VALUE r = rb_protect(obj_is_kind_of_body, (VALUE)&a, state);
    if (*state) return 0;
    return RTEST(r) ? 1 : 0;
}

int
rpyyarv_cleanup_with_error(uintptr_t err)
{
    rb_set_errinfo((VALUE)err);
    return ruby_cleanup(6);      /* RUBY_TAG_RAISE */
}

struct hash_args {
    VALUE hash;
    VALUE key;
    VALUE val;
    long  capa;
};

static VALUE
hash_new_capa_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_hash_new_capa(p->capa);
}

uintptr_t
rpyyarv_hash_new_capa(long capa, int *state)
{
    struct hash_args a;
    a.capa = capa;
    *state = 0;
    VALUE r = rb_protect(hash_new_capa_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
hash_aset_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_hash_aset(p->hash, p->key, p->val);
}

void
rpyyarv_hash_aset(uintptr_t hash, uintptr_t key, uintptr_t val, int *state)
{
    struct hash_args a;
    a.hash = (VALUE)hash;
    a.key = (VALUE)key;
    a.val = (VALUE)val;
    *state = 0;
    rb_protect(hash_aset_body, (VALUE)&a, state);
}

static VALUE
hash_resurrect_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_hash_dup(p->hash);
}

uintptr_t
rpyyarv_hash_resurrect(uintptr_t hash, int *state)
{
    struct hash_args a;
    a.hash = (VALUE)hash;
    *state = 0;
    VALUE r = rb_protect(hash_resurrect_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

long
rpyyarv_hash_size(uintptr_t hash)
{
    /* Not RHASH_SIZE: internal/hash.h undefines it. */
    return (long)rb_hash_size_num((VALUE)hash);
}

static VALUE
hash_lookup_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_hash_lookup2(p->hash, p->key, Qundef);
}

uintptr_t
rpyyarv_hash_lookup(uintptr_t hash, uintptr_t key, int *state)
{
    struct hash_args a;
    a.hash = (VALUE)hash;
    a.key = (VALUE)key;
    *state = 0;
    VALUE r = rb_protect(hash_lookup_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qundef;
    return (uintptr_t)r;
}

static VALUE
hash_delete_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_hash_delete(p->hash, p->key);
}

void
rpyyarv_hash_delete(uintptr_t hash, uintptr_t key, int *state)
{
    struct hash_args a;
    a.hash = (VALUE)hash;
    a.key = (VALUE)key;
    *state = 0;
    rb_protect(hash_delete_body, (VALUE)&a, state);
}

static VALUE
hash_aref_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_hash_aref(p->hash, p->key);
}

/* Hash#[] whole: hit, miss and the default value or proc, in one protected call; _v apart from the C-string-keyed rpyyarv_hash_aref above. */
uintptr_t
rpyyarv_hash_aref_v(uintptr_t hash, uintptr_t key, int *state)
{
    struct hash_args a;
    a.hash = (VALUE)hash;
    a.key = (VALUE)key;
    *state = 0;
    VALUE r = rb_protect(hash_aref_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* An immediate or String key hashes and compares in C, so a plain lookup cannot reenter Ruby; Qundef on miss, defaults not consulted. */
uintptr_t
rpyyarv_hash_lookup_fast(uintptr_t hash, uintptr_t key)
{
    return (uintptr_t)rb_hash_lookup2((VALUE)hash, (VALUE)key, Qundef);
}

/* As above for store; the caller already checked the frozen bit. */
uintptr_t
rpyyarv_hash_aset_fast(uintptr_t hash, uintptr_t key, uintptr_t val)
{
    return (uintptr_t)rb_hash_aset((VALUE)hash, (VALUE)key, (VALUE)val);
}

static int
hash_pairs_i(VALUE key, VALUE val, VALUE out)
{
    rb_ary_push(out, key);
    rb_ary_push(out, val);
    return ST_CONTINUE;
}

static VALUE
hash_pairs_body(VALUE h)
{
    VALUE out = rb_ary_new_capa(2 * (long)rb_hash_size_num(h));
    rb_hash_foreach(h, hash_pairs_i, out);
    return out;
}

/* [k0, v0, k1, v1, ...] in entry order: one call and one Array where keys-then-aref cost a C call per key. */
uintptr_t
rpyyarv_hash_pairs(uintptr_t hash, int *state)
{
    *state = 0;
    VALUE r = rb_protect(hash_pairs_body, (VALUE)hash, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

struct alias_var_args {
    VALUE sym1;
    VALUE sym2;
};

static VALUE
alias_variable_body(VALUE argp)
{
    struct alias_var_args *a = (struct alias_var_args *)argp;
    rb_alias_variable(SYM2ID(a->sym1), SYM2ID(a->sym2));
    return Qnil;
}

/* `alias $new $old` (vm.c m_core_set_variable_alias). */
uintptr_t
rpyyarv_alias_variable(uintptr_t sym1, uintptr_t sym2, int *state)
{
    struct alias_var_args a;
    a.sym1 = (VALUE)sym1;
    a.sym2 = (VALUE)sym2;
    *state = 0;
    VALUE r = rb_protect(alias_variable_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
set_include_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_set_lookup(p->hash, p->key) ? Qtrue : Qfalse;
}

/* Set#include? of an exact core Set; the element's #hash can be Ruby code, so protected. */
uintptr_t
rpyyarv_set_include(uintptr_t set, uintptr_t elt, int *state)
{
    VALUE s = (VALUE)set;
    struct hash_args a;
    *state = 0;
    if (SPECIAL_CONST_P(s) || rb_class_of(s) != rb_cSet)
        return (uintptr_t)Qundef;
    a.hash = s;
    a.key = (VALUE)elt;
    VALUE r = rb_protect(set_include_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
str_push_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_str_concat(p->hash, p->key);
}

/* String#<< of a String needing what the raw arm refuses: encoding negotiation or the frozen check, both of which can raise. */
uintptr_t
rpyyarv_str_push(uintptr_t str, uintptr_t other, int *state)
{
    struct hash_args a;
    *state = 0;
    if (!RB_TYPE_P((VALUE)str, T_STRING) || !RB_TYPE_P((VALUE)other, T_STRING))
        return (uintptr_t)Qundef;
    a.hash = (VALUE)str;
    a.key = (VALUE)other;
    VALUE r = rb_protect(str_push_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* Integer#to_s with no base argument: rb_fix2str never re-enters Ruby for a FIXNUM. */
uintptr_t
rpyyarv_int_to_s(uintptr_t v)
{
    if (!FIXNUM_P((VALUE)v)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_fix2str((VALUE)v, 10);
}

/* String#casecmp of two 7-bit Strings: the ASCII fold CRuby's own uses there. */
uintptr_t
rpyyarv_str_casecmp(uintptr_t a, uintptr_t b)
{
    VALUE s1 = (VALUE)a, s2 = (VALUE)b;
    const char *p1, *p2;
    long l1, l2, i, n;
    if (!RB_TYPE_P(s1, T_STRING) || !RB_TYPE_P(s2, T_STRING))
        return (uintptr_t)Qundef;
    if (rb_enc_str_coderange(s1) != ENC_CODERANGE_7BIT ||
        rb_enc_str_coderange(s2) != ENC_CODERANGE_7BIT)
        return (uintptr_t)Qundef;
    p1 = RSTRING_PTR(s1); p2 = RSTRING_PTR(s2);
    l1 = RSTRING_LEN(s1); l2 = RSTRING_LEN(s2);
    n = l1 < l2 ? l1 : l2;
    for (i = 0; i < n; i++) {
        int c1 = p1[i], c2 = p2[i];
        if (c1 >= 'A' && c1 <= 'Z') c1 += 32;
        if (c2 >= 'A' && c2 <= 'Z') c2 += 32;
        if (c1 != c2) return (uintptr_t)INT2FIX(c1 < c2 ? -1 : 1);
    }
    if (l1 != l2) return (uintptr_t)INT2FIX(l1 < l2 ? -1 : 1);
    return (uintptr_t)INT2FIX(0);
}

struct gsub2_args {
    VALUE recv;
    VALUE pat;
    VALUE rep;
    ID mid;
};

static VALUE
str_gsub2_body(VALUE argp)
{
    struct gsub2_args *a = (struct gsub2_args *)argp;
    VALUE argv[2];
    argv[0] = a->pat;
    argv[1] = a->rep;
    return rb_funcallv(a->recv, a->mid, 2, argv);
}

/* String#gsub/gsub!/sub/sub! for a Regexp|String pattern and a String replacement with no backreference escape and no block: rb_funcallv still runs the real method (so a redefined pattern-to-source coercion is honoured, and gsub/sub set $~ exactly as they always did), but skips RPyYARV's own dispatch bookkeeping; the replacement writes no backref itself and calls no Ruby method, so only encoding negotiation and Regexp.timeout can still raise, both under rb_protect. */
uintptr_t
rpyyarv_str_gsub2(uintptr_t str, uintptr_t pat, uintptr_t rep, uintptr_t mid,
                  int *state)
{
    VALUE s = (VALUE)str, p = (VALUE)pat, r = (VALUE)rep;
    struct gsub2_args a;
    const char *rp;
    long rl;
    *state = 0;
    if (!RB_TYPE_P(s, T_STRING) || !RB_TYPE_P(r, T_STRING))
        return (uintptr_t)Qundef;
    if (!RB_TYPE_P(p, T_REGEXP) && !RB_TYPE_P(p, T_STRING))
        return (uintptr_t)Qundef;
    RSTRING_GETMEM(r, rp, rl);
    if (memchr(rp, '\\', rl))
        return (uintptr_t)Qundef;
    if (!rb_enc_compatible(s, p) || !rb_enc_compatible(s, r))
        return (uintptr_t)Qundef;
    a.recv = s; a.pat = p; a.rep = r; a.mid = (ID)mid;
    {
        VALUE ret = rb_protect(str_gsub2_body, (VALUE)&a, state);
        if (*state) return (uintptr_t)Qnil;
        return (uintptr_t)ret;
    }
}

/* String#<=> for two Strings. */
uintptr_t
rpyyarv_str_cmp(uintptr_t a, uintptr_t b)
{
    if (!RB_TYPE_P((VALUE)a, T_STRING) || !RB_TYPE_P((VALUE)b, T_STRING))
        return (uintptr_t)Qundef;
    return (uintptr_t)INT2FIX(rb_str_cmp((VALUE)a, (VALUE)b));
}

/* String#downcase/#upcase and bang forms for 7-bit strings: a byte map. */
static uintptr_t
str_change_case(uintptr_t str, int up, int bang)
{
    VALUE s = (VALUE)str;
    long i, len;
    char *p;
    int changed = 0;
    if (!RB_TYPE_P(s, T_STRING)) return (uintptr_t)Qundef;
    if (rb_enc_str_coderange(s) != ENC_CODERANGE_7BIT)
        return (uintptr_t)Qundef;
    if (bang && OBJ_FROZEN(s)) return (uintptr_t)Qundef;
    if (!bang) s = rb_str_dup(s);
    rb_str_modify(s);
    p = RSTRING_PTR(s);
    len = RSTRING_LEN(s);
    for (i = 0; i < len; i++) {
        char c = p[i];
        if (up ? (c >= 'a' && c <= 'z') : (c >= 'A' && c <= 'Z')) {
            p[i] = up ? c - 32 : c + 32;
            changed = 1;
        }
    }
    if (bang && !changed) return (uintptr_t)Qnil;
    return (uintptr_t)s;
}

uintptr_t
rpyyarv_str_downcase(uintptr_t s) { return str_change_case(s, 0, 0); }
uintptr_t
rpyyarv_str_downcase_bang(uintptr_t s) { return str_change_case(s, 0, 1); }
uintptr_t
rpyyarv_str_upcase(uintptr_t s) { return str_change_case(s, 1, 0); }
uintptr_t
rpyyarv_str_upcase_bang(uintptr_t s) { return str_change_case(s, 1, 1); }

/* Symbol#to_s: a fresh mutable copy of the fstring. */
uintptr_t
rpyyarv_sym_to_s(uintptr_t v)
{
    if (!SYMBOL_P((VALUE)v)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_str_dup(rb_sym2str((VALUE)v));
}

/* String#dup on the exact class, whose initialize_copy is C. */
uintptr_t
rpyyarv_str_dup(uintptr_t v)
{
    VALUE s = (VALUE)v;
    if (!RB_TYPE_P(s, T_STRING) || rb_obj_class(s) != rb_cString)
        return (uintptr_t)Qundef;
    return (uintptr_t)rb_str_dup(s);
}

/* String#start_with? for one String prefix of the same encoding: a byte compare, nothing to raise. */
uintptr_t
rpyyarv_str_start_with(uintptr_t str, uintptr_t prefix)
{
    VALUE s = (VALUE)str;
    VALUE p = (VALUE)prefix;
    long ls, lp;
    if (!RB_TYPE_P(s, T_STRING) || !RB_TYPE_P(p, T_STRING))
        return (uintptr_t)Qundef;
    if (ENCODING_GET(s) != ENCODING_GET(p))
        return (uintptr_t)Qundef;
    ls = RSTRING_LEN(s);
    lp = RSTRING_LEN(p);
    if (lp > ls) return (uintptr_t)Qfalse;
    return memcmp(RSTRING_PTR(s), RSTRING_PTR(p), lp) == 0
        ? (uintptr_t)Qtrue : (uintptr_t)Qfalse;
}

static VALUE
to_hash_type_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    /* What rb_to_hash_type is (hash.c:1869); that one is not exported. */
    return rb_convert_type(p->hash, T_HASH, "Hash", "to_hash");
}

uintptr_t
rpyyarv_to_hash_type(uintptr_t v, int *state)
{
    struct hash_args a;
    a.hash = (VALUE)v;
    *state = 0;
    VALUE r = rb_protect(to_hash_type_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

static VALUE
hash_keys_body(VALUE argp)
{
    struct hash_args *p = (struct hash_args *)argp;
    return rb_funcall(p->hash, rb_intern("keys"), 0);
}

uintptr_t
rpyyarv_hash_keys(uintptr_t hash, int *state)
{
    struct hash_args a;
    a.hash = (VALUE)hash;
    *state = 0;
    VALUE r = rb_protect(hash_keys_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* rb_check_to_array is internal; this is the same to_a conversion. */
static VALUE
check_to_array(VALUE v)
{
    return rb_check_convert_type(v, T_ARRAY, "Array", "to_a");
}

struct splat_args {
    VALUE ary;
    int   flag;
};

/* vm_splat_array, minus the frozen-empty-array shortcut it takes at flag==0. */
static VALUE
splat_array_body(VALUE argp)
{
    struct splat_args *p = (struct splat_args *)argp;
    VALUE tmp;
    if (NIL_P(p->ary)) return rb_ary_new();
    /* to_a, as rb_check_to_array does; to_ary would leave a Range as [range]. */
    tmp = check_to_array(p->ary);
    if (NIL_P(tmp)) return rb_ary_new3(1, p->ary);
    if (p->flag) return rb_ary_dup(tmp);
    return tmp;
}

uintptr_t
rpyyarv_splat_array(uintptr_t ary, int flag, int *state)
{
    struct splat_args a;
    a.ary = (VALUE)ary;
    a.flag = flag;
    *state = 0;
    VALUE r = rb_protect(splat_array_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

struct concat_args {
    VALUE ary1, ary2;
    int   to;
};

/* vm_concat_array and vm_concat_to_array (vm_insnhelper.c:5692). */
static VALUE
concat_array_body(VALUE argp)
{
    struct concat_args *p = (struct concat_args *)argp;
    VALUE tmp1, tmp2;
    if (p->to) {
        if (NIL_P(p->ary2)) return p->ary1;
        tmp2 = check_to_array(p->ary2);
        if (NIL_P(tmp2)) return rb_ary_push(p->ary1, p->ary2);
        return rb_ary_concat(p->ary1, tmp2);
    }
    tmp1 = check_to_array(p->ary1);
    tmp2 = check_to_array(p->ary2);
    if (NIL_P(tmp1)) tmp1 = rb_ary_new3(1, p->ary1);
    if (tmp1 == p->ary1) tmp1 = rb_ary_dup(p->ary1);
    if (NIL_P(tmp2)) return rb_ary_push(tmp1, p->ary2);
    return rb_ary_concat(tmp1, tmp2);
}

uintptr_t
rpyyarv_concat_array(uintptr_t ary1, uintptr_t ary2, int to, int *state)
{
    struct concat_args a;
    a.ary1 = (VALUE)ary1;
    a.ary2 = (VALUE)ary2;
    a.to = to;
    *state = 0;
    VALUE r = rb_protect(concat_array_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* FrozenCore is hidden: rb_set_class_path names it but defines no constant (vm.c:4274), so only the exported variable reaches it. */
extern VALUE rb_mRubyVMFrozenCore;

uintptr_t
rpyyarv_vm_core(void)
{
    return (uintptr_t)rb_mRubyVMFrozenCore;
}

struct arity_args {
    int given;
    int min;
    int max;
};

struct kwerr_args {
    const char *kind;
    VALUE keys;
};

/* rb_keyword_error_new (class.c:2859), which libruby does not export. */
static VALUE
keyword_error_body(VALUE argp)
{
    struct kwerr_args *p = (struct kwerr_args *)argp;
    long i = 0, len = RARRAY_LEN(p->keys);
    VALUE mesg = rb_sprintf("%s keyword%.*s", p->kind, len > 1, "s");

    if (len > 0) {
        rb_str_cat_cstr(mesg, ": ");
        while (1) {
            rb_str_append(mesg, rb_inspect(RARRAY_AREF(p->keys, i)));
            if (++i >= len) break;
            rb_str_cat_cstr(mesg, ", ");
        }
    }
    return rb_exc_new_str(rb_eArgError, mesg);
}

/* rb_arity_error_new (vm_insnhelper.c:487), which is static there. */
static VALUE
arity_error_body(VALUE argp)
{
    struct arity_args *p = (struct arity_args *)argp;
    VALUE mesg = rb_sprintf("wrong number of arguments (given %d, expected %d",
                            p->given, p->min);
    if (p->min == p->max) {
        /* max is not needed */
    }
    else if (p->max < 0) {
        rb_str_cat_cstr(mesg, "+");
    }
    else {
        rb_str_catf(mesg, "..%d", p->max);
    }
    rb_str_cat_cstr(mesg, ")");
    return rb_exc_new_str(rb_eArgError, mesg);
}

struct localjump_args {
    const char *mesg;
    VALUE value;
    int reason;
};

/* make_localjump_error (vm.c:2175), which is static there. */
static VALUE
local_jump_error_body(VALUE argp)
{
    struct localjump_args *p = (struct localjump_args *)argp;
    VALUE exc = rb_exc_new2(rb_eLocalJumpError, p->mesg);
    const char *reason = "noreason";
    switch (p->reason) {
      case 1: reason = "return"; break;
      case 2: reason = "break";  break;
      case 3: reason = "next";   break;
      case 4: reason = "retry";  break;
      case 5: reason = "redo";   break;
      default: break;
    }
    rb_iv_set(exc, "@exit_value", p->value);
    rb_iv_set(exc, "@reason", ID2SYM(rb_intern(reason)));
    return exc;
}

uintptr_t
rpyyarv_local_jump_error(const char *mesg, uintptr_t value, int reason,
                         int *state)
{
    struct localjump_args a;
    a.mesg = mesg;
    a.value = (VALUE)value;
    a.reason = reason;
    *state = 0;
    VALUE r = rb_protect(local_jump_error_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* rb_keyword_error_new is class.c's, the same one vm_args.c raises with, so the message matches CRuby's byte for byte. */
uintptr_t
rpyyarv_keyword_error(const char *kind, uintptr_t keys, int *state)
{
    struct kwerr_args a;
    a.kind = kind;
    a.keys = (VALUE)keys;
    *state = 0;
    VALUE r = rb_protect(keyword_error_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

uintptr_t
rpyyarv_arity_error(int given, int min, int max, int *state)
{
    struct arity_args a;
    a.given = given;
    a.min = min;
    a.max = max;
    *state = 0;
    VALUE r = rb_protect(arity_error_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* ruby_vm_redefined_flag is hidden in libruby so BASIC_OP_UNREDEFINED_P is unreachable; rb_method_basic_definition_p asks the same question per entry (vm.c:2341), one bit per (class, operator) pair in the order helpers.py names them. */
uintptr_t
rpyyarv_bop_mask(int *count)
{
    uintptr_t mask = 0;
    int i = 0;

#define BOP(klass, name)                                              \
    do {                                                              \
        if (!rb_method_basic_definition_p((klass), rb_intern(name)))  \
            mask |= ((uintptr_t)1 << i);                              \
        i++;                                                          \
    } while (0)

    BOP(rb_cInteger, "+");
    BOP(rb_cInteger, "-");
    BOP(rb_cInteger, "*");
    BOP(rb_cInteger, "/");
    BOP(rb_cInteger, "%");
    BOP(rb_cInteger, "==");
    BOP(rb_cInteger, "<");
    BOP(rb_cInteger, "<=");
    BOP(rb_cInteger, ">");
    BOP(rb_cInteger, ">=");
    BOP(rb_cInteger, "&");
    BOP(rb_cInteger, "|");
    BOP(rb_cInteger, "^");
    BOP(rb_cInteger, ">>");
    BOP(rb_cArray, "[]");
    BOP(rb_cArray, "[]=");
    BOP(rb_cArray, "length");
    BOP(rb_cArray, "size");
    BOP(rb_cArray, "empty?");
    BOP(rb_cSymbol, "==");
    BOP(rb_cRange, "begin");
    BOP(rb_cRange, "end");
    BOP(rb_cRange, "exclude_end?");
    BOP(rb_cFloat, "+");
    BOP(rb_cFloat, "-");
    BOP(rb_cFloat, "*");
    BOP(rb_cFloat, "/");
    BOP(rb_cFloat, "<");
    BOP(rb_cFloat, "<=");
    BOP(rb_cFloat, ">");
    BOP(rb_cFloat, ">=");
    BOP(rb_cFloat, "==");
    /* Math.sqrt is a singleton method of the module, so the pair is its metaclass. */
    BOP(CLASS_OF(rb_mMath), "sqrt");
    BOP(CLASS_OF(rb_cArray), "new");
    BOP(rb_cArray, "initialize");
    BOP(rb_cNilClass, "nil?");
    BOP(rb_cString, "freeze");
    BOP(rb_cString, "==");
    BOP(rb_mKernel, "send");
    BOP(rb_cBasicObject, "__send__");
    BOP(rb_cArray, "<<");
    BOP(rb_cFloat, "**");
    BOP(rb_cInteger, "**");
    BOP(CLASS_OF(rb_mMath), "cos");
    BOP(rb_cInteger, "to_f");
    BOP(rb_cFloat, "to_f");
    BOP(rb_cSymbol, "name");
    BOP(rb_cBasicObject, "initialize");
    BOP(rb_cString, "<<");
    BOP(rb_mKernel, "nil?");
    BOP(rb_cBasicObject, "instance_eval");
    BOP(rb_cBasicObject, "instance_exec");
    BOP(rb_cHash, "[]");
    BOP(rb_cString, "to_s");
    BOP(rb_mKernel, "===");
    BOP(rb_mKernel, "kind_of?");
    BOP(rb_mKernel, "is_a?");
    BOP(rb_cHash, "[]=");
    BOP(rb_cHash, "key?");
    BOP(rb_cHash, "has_key?");
    BOP(rb_cSet, "include?");
    BOP(rb_cString, "===");
    BOP(rb_cString, "start_with?");
#undef BOP

    /* The count is an out-parameter, so every bit of the word stays available to the mask. */
    *count = i;
    return mask;
}

/* Qundef for anything but a direct Range instance, so an overriding subclass falls back to normal dispatch; fields come from internal/range.h, so no RRange layout is compiled into the RPython side. */
uintptr_t
rpyyarv_range_part(uintptr_t range, int which)
{
    VALUE r = (VALUE)range;
    if (SPECIAL_CONST_P(r) || !RB_TYPE_P(r, T_STRUCT)) return (uintptr_t)Qundef;
    if (rb_obj_class(r) != rb_cRange) return (uintptr_t)Qundef;
    switch (which) {
      case RPYYARV_RANGE_BEG:  return (uintptr_t)RANGE_BEG(r);
      case RPYYARV_RANGE_END:  return (uintptr_t)RANGE_END(r);
      case RPYYARV_RANGE_EXCL: return (uintptr_t)RANGE_EXCL(r);
      default: return (uintptr_t)Qundef;
    }
}

struct struct_member_args {
    VALUE klass;
    ID id;
};

static VALUE
struct_member_index_body(VALUE argp)
{
    struct struct_member_args *a = (struct struct_member_args *)argp;
    VALUE members = rb_struct_s_members(a->klass);
    long i;
    for (i = 0; i < RARRAY_LEN(members); i++) {
        if (SYM2ID(RARRAY_AREF(members, i)) == a->id) return LONG2FIX(i);
    }
    return INT2FIX(-1);
}

int
rpyyarv_struct_member_index(uintptr_t klass, uintptr_t id)
{
    struct struct_member_args a;
    int state = 0;
    VALUE out;
    a.klass = (VALUE)klass;
    a.id = (ID)id;
    out = rb_protect(struct_member_index_body, (VALUE)&a, &state);
    if (state) {
        rb_set_errinfo(Qnil);
        return -1;
    }
    return FIX2INT(out);
}

uintptr_t
rpyyarv_struct_get(uintptr_t obj, int index)
{
    VALUE st = (VALUE)obj;
    if (SPECIAL_CONST_P(st) || !RB_TYPE_P(st, T_STRUCT) ||
        index < 0 || index >= RSTRUCT_LEN(st)) return (uintptr_t)Qundef;
    return (uintptr_t)RSTRUCT_GET(st, index);
}

void
rpyyarv_struct_set(uintptr_t obj, int index, uintptr_t val)
{
    RSTRUCT_SET((VALUE)obj, index, (VALUE)val);
}

uintptr_t
rpyyarv_class_ivar_get(uintptr_t obj, uintptr_t id)
{
    VALUE recv = (VALUE)obj;
    if (SPECIAL_CONST_P(recv) ||
        !(RB_TYPE_P(recv, T_CLASS) || RB_TYPE_P(recv, T_MODULE)))
        return (uintptr_t)Qundef;
    return (uintptr_t)rb_attr_get(recv, (ID)id);
}

int
rpyyarv_ivar_defined(uintptr_t obj, uintptr_t id)
{
    return RTEST(rb_ivar_defined((VALUE)obj, (ID)id)) ? 1 : 0;
}

int
rpyyarv_const_defined(uintptr_t klass, uintptr_t id, int inherit)
{
    return (inherit ? rb_const_defined((VALUE)klass, (ID)id)
                    : rb_const_defined_at((VALUE)klass, (ID)id)) ? 1 : 0;
}

int
rpyyarv_method_defined(uintptr_t obj, uintptr_t id, int include_private)
{
    return rb_obj_respond_to((VALUE)obj, (ID)id, include_private) ? 1 : 0;
}

uintptr_t
rpyyarv_str_getbyte(uintptr_t str, uintptr_t index)
{
    VALUE s = (VALUE)str;
    VALUE i = (VALUE)index;
    long offset;
    long len;
    if (!RB_TYPE_P(s, T_STRING) || !RB_FIXNUM_P(i)) return (uintptr_t)Qundef;
    offset = FIX2LONG(i);
    len = RSTRING_LEN(s);
    if (offset < 0) offset += len;
    if (offset < 0 || offset >= len) return (uintptr_t)Qnil;
    return (uintptr_t)INT2FIX((unsigned char)RSTRING_PTR(s)[offset]);
}

static VALUE
class_le_body(VALUE argp)
{
    struct owner_args *p = (struct owner_args *)argp;
    /* Module#<= is kind_of? asked of the class instead of an instance: true when klass is the target or below it, nil when they are unrelated. */
    return rb_funcall(p->klass, rb_intern("<="), 1, (VALUE)p->id);
}

int
rpyyarv_class_le(uintptr_t klass, uintptr_t target)
{
    struct owner_args a;
    int state = 0;
    VALUE r;
    a.klass = (VALUE)klass;
    a.id = (ID)target;
    r = rb_protect(class_le_body, (VALUE)&a, &state);
    if (state) {
        rb_set_errinfo(Qnil);
        return -1;
    }
    if (NIL_P(r)) return 0;
    return RTEST(r) ? 1 : 0;
}

uintptr_t
rpyyarv_str_append(uintptr_t str, uintptr_t other)
{
    VALUE s = (VALUE)str;
    VALUE o = (VALUE)other;
    if (!RB_TYPE_P(s, T_STRING) || RB_OBJ_FROZEN_RAW(s)) return (uintptr_t)Qundef;
    if (RB_FIXNUM_P(o)) {
        /* rb_str_concat's codepoint arm, only where a codepoint is one byte: a binary receiver and a byte value. */
        long n = FIX2LONG(o);
        char c;
        if (n < 0 || n > 0xff) return (uintptr_t)Qundef;
        if (ENCODING_GET(s) != rb_ascii8bit_encindex()) return (uintptr_t)Qundef;
        c = (char)n;
        return (uintptr_t)rb_str_cat(s, &c, 1);
    }
    if (!RB_TYPE_P(o, T_STRING)) return (uintptr_t)Qundef;
    /* Same encoding: rb_str_buf_append would otherwise negotiate one and can raise. */
    if (ENCODING_GET(s) != ENCODING_GET(o)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_str_buf_append(s, o);
}

uintptr_t
rpyyarv_str_setbyte(uintptr_t str, uintptr_t index, uintptr_t value)
{
    VALUE s = (VALUE)str;
    VALUE i = (VALUE)index;
    VALUE v = (VALUE)value;
    long offset;
    long len;
    if (!RB_TYPE_P(s, T_STRING) || !RB_FIXNUM_P(i) || !RB_FIXNUM_P(v) ||
        RB_OBJ_FROZEN_RAW(s)) return (uintptr_t)Qundef;
    offset = FIX2LONG(i);
    len = RSTRING_LEN(s);
    if (offset < 0) offset += len;
    if (offset < 0 || offset >= len) return (uintptr_t)Qundef;
    rb_str_modify(s);
    RSTRING_PTR(s)[offset] = (char)(FIX2LONG(v) & 0xff);
    ENC_CODERANGE_CLEAR(s);
    return (uintptr_t)v;
}

uintptr_t
rpyyarv_str_concat(int n, const uintptr_t *parts)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    VALUE out;
    int i;
    if (n < 0 || n > RPYYARV_MAX_ARGC) return (uintptr_t)Qundef;
    for (i = 0; i < n; i++) buf[i] = (VALUE)parts[i];
    out = rb_str_new(0, 0);
    for (i = 0; i < n; i++) rb_str_append(out, buf[i]);
    return (uintptr_t)out;
}

/* Only .rb: an extension RPyYARV cannot compile itself stays CRuby's. */
static const char *const rpyyarv_rb_ext[] = {".rb", NULL};

struct require_args {
    VALUE fname;
    VALUE path;
    int kind;
};

/* load.c:1067 search_required, restricted to the cases that answer 'r'. */
static VALUE
require_resolve_body(VALUE argp)
{
    struct require_args *a = (struct require_args *)argp;
    VALUE fname = rb_get_path(a->fname);
    const char *ftptr = RSTRING_PTR(fname);
    const char *ext = strrchr(ftptr, '.');
    const char *loading;
    VALUE tmp;

    a->kind = RPYYARV_REQ_FOREIGN;
    if (ext && !strchr(ext, '/')) {
        if (strcmp(ext, ".rb") != 0) return Qnil;
        if (rb_feature_provided(ftptr, &loading)) {
            a->kind = RPYYARV_REQ_LOADED;
            return Qnil;
        }
        tmp = rb_find_file(fname);
        if (!tmp) return Qnil;
    }
    else {
        if (rb_feature_provided(ftptr, &loading)) {
            a->kind = RPYYARV_REQ_LOADED;
            return Qnil;
        }
        tmp = fname;
        if (!rb_find_file_ext(&tmp, rpyyarv_rb_ext)) return Qnil;
    }
    if (rb_feature_provided(RSTRING_PTR(tmp), &loading)) {
        a->kind = RPYYARV_REQ_LOADED;
        return Qnil;
    }
    a->path = tmp;
    a->kind = RPYYARV_REQ_RB;
    return Qnil;
}

int
rpyyarv_require_resolve(uintptr_t fname, uintptr_t *path_out, int *state)
{
    struct require_args a;
    a.fname = (VALUE)fname;
    a.path = Qnil;
    a.kind = RPYYARV_REQ_FOREIGN;
    *state = 0;
    rb_protect(require_resolve_body, (VALUE)&a, state);
    if (*state) return RPYYARV_REQ_FOREIGN;
    *path_out = (uintptr_t)a.path;
    return a.kind;
}

static VALUE
provide_body(VALUE argp)
{
    /* Not rb_provide: rb_fstring_cstr keeps the caller's bytes, and these belong to a String the GC frees under it. */
    rb_ary_push(rb_gv_get("$LOADED_FEATURES"),
                rb_str_new_frozen(rb_get_path((VALUE)argp)));
    return Qnil;
}

void
rpyyarv_provide(uintptr_t path, int *state)
{
    *state = 0;
    rb_protect(provide_body, (VALUE)path, state);
}

static VALUE
absolute_path_body(VALUE argp)
{
    struct obj_args *p = (struct obj_args *)argp;
    return rb_file_absolute_path(p->a, p->b);
}

uintptr_t
rpyyarv_absolute_path(uintptr_t fname, uintptr_t base, int *state)
{
    struct obj_args a;
    a.a = (VALUE)fname;
    a.b = (VALUE)base;
    *state = 0;
    VALUE r = rb_protect(absolute_path_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* String#length: rb_str_strlen counts characters without allocating. */
uintptr_t
rpyyarv_str_length(uintptr_t v)
{
    if (!RB_TYPE_P((VALUE)v, T_STRING)) return (uintptr_t)Qundef;
    return (uintptr_t)LONG2FIX(rb_str_strlen((VALUE)v));
}

/* String#tr with two single-byte sets on a 7-bit string: mail's dasherize. */
uintptr_t
rpyyarv_str_tr1(uintptr_t str, uintptr_t from, uintptr_t to)
{
    VALUE s = (VALUE)str, f = (VALUE)from, t = (VALUE)to;
    VALUE out;
    char *p, cf, ct;
    long i, len;
    if (!RB_TYPE_P(s, T_STRING) || !RB_TYPE_P(f, T_STRING) ||
        !RB_TYPE_P(t, T_STRING))
        return (uintptr_t)Qundef;
    if (RSTRING_LEN(f) != 1 || RSTRING_LEN(t) != 1)
        return (uintptr_t)Qundef;
    cf = RSTRING_PTR(f)[0];
    ct = RSTRING_PTR(t)[0];
    /* ^ or - or \ would make the one byte a pattern, not a byte. */
    if (cf == '^' || cf == '-' || cf == '\\' ||
        ct == '^' || ct == '-' || ct == '\\')
        return (uintptr_t)Qundef;
    if (rb_enc_str_coderange(s) != ENC_CODERANGE_7BIT ||
        (unsigned char)cf > 127 || (unsigned char)ct > 127)
        return (uintptr_t)Qundef;
    out = rb_str_dup(s);
    rb_str_modify(out);
    p = RSTRING_PTR(out);
    len = RSTRING_LEN(out);
    for (i = 0; i < len; i++) {
        if (p[i] == cf) p[i] = ct;
    }
    return (uintptr_t)out;
}

/* String#index of a String needle in a 7-bit haystack, no offset. */
uintptr_t
rpyyarv_str_index_of(uintptr_t str, uintptr_t needle)
{
    VALUE s = (VALUE)str, n = (VALUE)needle;
    const char *ps, *pn, *found;
    long ls, ln;
    if (!RB_TYPE_P(s, T_STRING) || !RB_TYPE_P(n, T_STRING))
        return (uintptr_t)Qundef;
    if (rb_enc_str_coderange(s) != ENC_CODERANGE_7BIT ||
        rb_enc_str_coderange(n) != ENC_CODERANGE_7BIT)
        return (uintptr_t)Qundef;
    ps = RSTRING_PTR(s); ls = RSTRING_LEN(s);
    pn = RSTRING_PTR(n); ln = RSTRING_LEN(n);
    if (ln == 0) return (uintptr_t)INT2FIX(0);
    if (ln > ls) return (uintptr_t)Qnil;
    found = memmem(ps, ls, pn, ln);
    if (!found) return (uintptr_t)Qnil;
    return (uintptr_t)LONG2FIX((long)(found - ps));
}

static OnigPosition
matchp_search(regex_t *reg, VALUE str, struct re_registers *regs, void *args_v)
{
    const char *ptr;
    long len;
    (void)args_v;
    RSTRING_GETMEM(str, ptr, len);
    return onig_search(reg, (const UChar *)ptr, (const UChar *)(ptr + len),
                       (const UChar *)ptr, (const UChar *)(ptr + len),
                       regs, ONIG_OPTION_NONE);
}

struct matchp_args {
    VALUE str;
    VALUE re;
};

static VALUE
str_match_p_body(VALUE argp)
{
    struct matchp_args *a = (struct matchp_args *)argp;
    return rb_reg_onig_match(a->re, a->str, matchp_search, NULL, NULL)
           == ONIG_MISMATCH ? Qfalse : Qtrue;
}

/* String#match? with a Regexp, no offset: writes no backref, so only the search itself runs under protect (encoding mismatch, Regexp.timeout). */
uintptr_t
rpyyarv_str_match_p(uintptr_t str, uintptr_t re, int *state)
{
    struct matchp_args a;
    VALUE r;
    *state = 0;
    if (!RB_TYPE_P((VALUE)str, T_STRING) || !RB_TYPE_P((VALUE)re, T_REGEXP))
        return (uintptr_t)Qundef;
    a.str = (VALUE)str;
    a.re = (VALUE)re;
    r = rb_protect(str_match_p_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

struct eq_tilde_args {
    VALUE str;
    VALUE re;
};

static VALUE
eq_tilde_body(VALUE argp)
{
    struct eq_tilde_args *a = (struct eq_tilde_args *)argp;
    return rb_reg_match(a->re, a->str);
}

/* String#=~ Regexp and Regexp#=~ String: rb_reg_match is the whole method (it sets $~ itself), tried in whichever operand order has a String and a Regexp. */
uintptr_t
rpyyarv_str_eq_tilde(uintptr_t a, uintptr_t b, int *state)
{
    struct eq_tilde_args args;
    VALUE va = (VALUE)a, vb = (VALUE)b;
    *state = 0;
    if (RB_TYPE_P(va, T_STRING) && CLASS_OF(vb) == rb_cRegexp) {
        args.str = va; args.re = vb;
    } else if (RB_TYPE_P(vb, T_STRING) && CLASS_OF(va) == rb_cRegexp) {
        args.str = vb; args.re = va;
    } else {
        return (uintptr_t)Qundef;
    }
    {
        VALUE ret = rb_protect(eq_tilde_body, (VALUE)&args, state);
        if (*state) return (uintptr_t)Qnil;
        return (uintptr_t)ret;
    }
}

/* Regexp#=== String: the same rb_reg_match core as =~, answered as true/false instead of a position. */
uintptr_t
rpyyarv_reg_eqq(uintptr_t re, uintptr_t str, int *state)
{
    struct eq_tilde_args args;
    VALUE r;
    *state = 0;
    if (CLASS_OF((VALUE)re) != rb_cRegexp || !RB_TYPE_P((VALUE)str, T_STRING))
        return (uintptr_t)Qundef;
    args.str = (VALUE)str; args.re = (VALUE)re;
    r = rb_protect(eq_tilde_body, (VALUE)&args, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)(NIL_P(r) ? Qfalse : Qtrue);
}

/* Regexp.last_match with no argument: rb_backref_get plus the rb_match_busy mark match_getter (re.c) also sets, so a later match cannot mutate this MatchData out from under it. */
uintptr_t
rpyyarv_last_match0(void)
{
    VALUE md = rb_backref_get();
    if (NIL_P(md)) return (uintptr_t)Qnil;
    rb_match_busy(md);
    return (uintptr_t)md;
}

/* Regexp.last_match(n) for a Fixnum n: rb_reg_nth_match answers nil for any out-of-range n, so nothing here can raise. */
uintptr_t
rpyyarv_last_match1(uintptr_t n)
{
    VALUE md;
    if (!FIXNUM_P((VALUE)n)) return (uintptr_t)Qundef;
    md = rb_backref_get();
    if (NIL_P(md)) return (uintptr_t)Qnil;
    return (uintptr_t)rb_reg_nth_match(FIX2INT((VALUE)n), md);
}

static VALUE
str_match_body(VALUE argp)
{
    struct eq_tilde_args *a = (struct eq_tilde_args *)argp;
    VALUE md;
    rb_reg_match(a->re, a->str);
    md = rb_backref_get();
    if (!NIL_P(md)) rb_match_busy(md);
    return md;
}

/* String#match with a Regexp pattern, no offset, no block: rb_reg_match sets $~, which is exactly what Regexp#match itself returns (rb_match_busy and all). */
uintptr_t
rpyyarv_str_match(uintptr_t str, uintptr_t re, int *state)
{
    struct eq_tilde_args args;
    VALUE r;
    *state = 0;
    if (!RB_TYPE_P((VALUE)str, T_STRING) || CLASS_OF((VALUE)re) != rb_cRegexp)
        return (uintptr_t)Qundef;
    args.str = (VALUE)str; args.re = (VALUE)re;
    r = rb_protect(str_match_body, (VALUE)&args, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

uintptr_t
rpyyarv_str_empty_p(uintptr_t v)
{
    if (!RB_TYPE_P((VALUE)v, T_STRING)) return (uintptr_t)Qundef;
    return (uintptr_t)(RSTRING_LEN((VALUE)v) == 0 ? Qtrue : Qfalse);
}

uintptr_t
rpyyarv_hash_empty_p(uintptr_t v)
{
    if (!RB_TYPE_P((VALUE)v, T_HASH)) return (uintptr_t)Qundef;
    return (uintptr_t)(rb_hash_size_num((VALUE)v) == 0 ? Qtrue : Qfalse);
}

/* String#-@: the deduplicated frozen copy, or the receiver when already interned. */
uintptr_t
rpyyarv_str_uminus(uintptr_t v)
{
    if (!RB_TYPE_P((VALUE)v, T_STRING)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_str_to_interned_str((VALUE)v);
}

uintptr_t
rpyyarv_ary_pop_fast(uintptr_t v)
{
    VALUE a = (VALUE)v;
    if (!RB_TYPE_P(a, T_ARRAY) || OBJ_FROZEN(a)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_ary_pop(a);
}

uintptr_t
rpyyarv_ary_shift_fast(uintptr_t v)
{
    VALUE a = (VALUE)v;
    if (!RB_TYPE_P(a, T_ARRAY) || OBJ_FROZEN(a)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_ary_shift(a);
}

uintptr_t
rpyyarv_ary_unshift1(uintptr_t v, uintptr_t elt)
{
    VALUE a = (VALUE)v;
    if (!RB_TYPE_P(a, T_ARRAY) || OBJ_FROZEN(a)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_ary_unshift(a, (VALUE)elt);
}

/* Array#freeze / Hash#freeze: OBJ_FREEZE_RAW cannot re-enter Ruby for either type. */
uintptr_t
rpyyarv_ary_hash_freeze(uintptr_t v)
{
    VALUE o = (VALUE)v;
    if (!RB_TYPE_P(o, T_ARRAY) && !RB_TYPE_P(o, T_HASH)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_obj_freeze(o);
}

static int
hash_keys_fast_i(VALUE key, VALUE val, VALUE out)
{
    (void)val;
    rb_ary_push(out, key);
    return ST_CONTINUE;
}

static VALUE
hash_keys_fast_body(VALUE h)
{
    VALUE out = rb_ary_new_capa((long)rb_hash_size_num(h));
    rb_hash_foreach(h, hash_keys_fast_i, out);
    return out;
}

/* Hash#keys in entry order, an rb_hash_foreach loop in place of rpyyarv_hash_keys's rb_funcall (that one stays, for the keyword-splat error path, which does not need the extra speed). */
uintptr_t
rpyyarv_hash_keys_fast(uintptr_t hash, int *state)
{
    *state = 0;
    VALUE r = rb_protect(hash_keys_fast_body, (VALUE)hash, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* Array#flatten! for literal-Array elements only (no #to_ary duck-typing, a known corner); nil if nothing to flatten, self otherwise; Q_UNDEF past one level of nesting or a frozen receiver. */
uintptr_t
rpyyarv_ary_flatten_bang1(uintptr_t v)
{
    VALUE a = (VALUE)v;
    VALUE out;
    long i, n, j, m;
    int any_array = 0, any_nested = 0;
    if (!RB_TYPE_P(a, T_ARRAY) || OBJ_FROZEN(a)) return (uintptr_t)Qundef;
    n = RARRAY_LEN(a);
    for (i = 0; i < n && !any_nested; i++) {
        VALUE e = RARRAY_AREF(a, i);
        if (RB_TYPE_P(e, T_ARRAY)) {
            any_array = 1;
            m = RARRAY_LEN(e);
            for (j = 0; j < m; j++) {
                if (RB_TYPE_P(RARRAY_AREF(e, j), T_ARRAY)) {
                    any_nested = 1;
                    break;
                }
            }
        }
    }
    if (any_nested) return (uintptr_t)Qundef;
    if (!any_array) return (uintptr_t)Qnil;
    out = rb_ary_new_capa(n);
    for (i = 0; i < n; i++) {
        VALUE e = RARRAY_AREF(a, i);
        if (RB_TYPE_P(e, T_ARRAY)) {
            m = RARRAY_LEN(e);
            for (j = 0; j < m; j++) rb_ary_push(out, RARRAY_AREF(e, j));
        } else {
            rb_ary_push(out, e);
        }
    }
    rb_ary_replace(a, out);
    return (uintptr_t)a;
}

uintptr_t
rpyyarv_ary_push1(uintptr_t v, uintptr_t elt)
{
    VALUE a = (VALUE)v;
    if (!RB_TYPE_P(a, T_ARRAY) || OBJ_FROZEN(a)) return (uintptr_t)Qundef;
    return (uintptr_t)rb_ary_push(a, (VALUE)elt);
}

/* Mirror of ext/strscan/strscan.c's struct strscanner, version-locked to this checkout's bundled strscan; ss_of verifies the TypedData name before trusting it. */
struct rpyyarv_ss {
    unsigned long flags;      /* bit 0: matched */
    VALUE str;
    long prev;
    long curr;
    struct re_registers regs;
    VALUE regex;
    bool fixed_anchor_p;
};

static const rb_data_type_t *ss_type;

static struct rpyyarv_ss *
ss_of(VALUE v)
{
    struct rpyyarv_ss *p;
    if (!RB_TYPE_P(v, T_DATA) || !RTYPEDDATA_P(v)) return NULL;
    if (RTYPEDDATA_TYPE(v) != ss_type) {
        if (strcmp(RTYPEDDATA_TYPE(v)->wrap_struct_name, "StringScanner"))
            return NULL;
        ss_type = RTYPEDDATA_TYPE(v);
    }
    p = RTYPEDDATA_DATA(v);
    if (!p || !RB_TYPE_P(p->str, T_STRING)) return NULL;
    return p;
}

uintptr_t
rpyyarv_ss_pos(uintptr_t v)
{
    struct rpyyarv_ss *p = ss_of((VALUE)v);
    if (!p) return (uintptr_t)Qundef;
    return (uintptr_t)LONG2FIX(p->curr);
}

uintptr_t
rpyyarv_ss_set_pos(uintptr_t v, uintptr_t posv)
{
    struct rpyyarv_ss *p = ss_of((VALUE)v);
    long i;
    if (!p || !FIXNUM_P((VALUE)posv)) return (uintptr_t)Qundef;
    i = FIX2LONG((VALUE)posv);
    if (i < 0) i += RSTRING_LEN(p->str);
    /* Out of range raises upstream. */
    if (i < 0 || i > RSTRING_LEN(p->str)) return (uintptr_t)Qundef;
    p->curr = i;
    return (uintptr_t)LONG2FIX(i);
}

uintptr_t
rpyyarv_ss_eos_p(uintptr_t v)
{
    struct rpyyarv_ss *p = ss_of((VALUE)v);
    if (!p) return (uintptr_t)Qundef;
    return (uintptr_t)(p->curr >= RSTRING_LEN(p->str) ? Qtrue : Qfalse);
}

uintptr_t
rpyyarv_ss_matched_size(uintptr_t v)
{
    struct rpyyarv_ss *p = ss_of((VALUE)v);
    if (!p) return (uintptr_t)Qundef;
    if (!(p->flags & 1UL)) return (uintptr_t)Qnil;
    return (uintptr_t)LONG2FIX(p->regs.end[0] - p->regs.beg[0]);
}

static OnigPosition
ss_match_head(regex_t *reg, VALUE str, struct re_registers *regs, void *args_v)
{
    struct rpyyarv_ss *p = args_v;
    const char *pbeg = RSTRING_PTR(p->str);
    long len = RSTRING_LEN(p->str);
    const UChar *target =
        (const UChar *)(p->fixed_anchor_p ? pbeg : pbeg + p->curr);
    (void)str;
    return onig_match(reg, target, (const UChar *)(pbeg + len),
                      (const UChar *)(pbeg + p->curr), regs, ONIG_OPTION_NONE);
}

struct ss_skip_args {
    struct rpyyarv_ss *p;
    VALUE re;
};

static VALUE
ss_skip_body(VALUE argp)
{
    struct ss_skip_args *a = (struct ss_skip_args *)argp;
    struct rpyyarv_ss *p = a->p;
    OnigPosition ret = rb_reg_onig_match(a->re, p->str, ss_match_head,
                                         p, &p->regs);
    if (ret == ONIG_MISMATCH) return Qnil;
    p->flags |= 1UL;
    p->prev = p->curr;
    if (p->fixed_anchor_p) {
        p->curr = p->regs.end[0];
        return LONG2FIX(p->regs.end[0] - p->prev);
    }
    p->curr += p->regs.end[0];
    return LONG2FIX(p->regs.end[0]);
}

/* StringScanner#skip with a Regexp: strscan_do_scan(headonly, succptr, no getstr). */
uintptr_t
rpyyarv_ss_skip(uintptr_t v, uintptr_t re, int *state)
{
    struct ss_skip_args a;
    struct rpyyarv_ss *p;
    VALUE r;
    *state = 0;
    p = ss_of((VALUE)v);
    if (!p || !RB_TYPE_P((VALUE)re, T_REGEXP)) return (uintptr_t)Qundef;
    p->flags &= ~1UL;
    RB_OBJ_WRITE((VALUE)v, &p->regex, (VALUE)re);
    a.p = p;
    a.re = (VALUE)re;
    r = rb_protect(ss_skip_body, (VALUE)&a, state);
    if (*state) return (uintptr_t)Qnil;
    return (uintptr_t)r;
}

/* String#byteslice with two Integers; rb_str_subseq indexes bytes and shares. */
uintptr_t
rpyyarv_str_byteslice2(uintptr_t str, uintptr_t begv, uintptr_t lenv)
{
    VALUE s = (VALUE)str;
    long beg, len, n;
    if (!RB_TYPE_P(s, T_STRING) || !FIXNUM_P((VALUE)begv)
        || !FIXNUM_P((VALUE)lenv))
        return (uintptr_t)Qundef;
    beg = FIX2LONG((VALUE)begv);
    len = FIX2LONG((VALUE)lenv);
    n = RSTRING_LEN(s);
    if (len < 0) return (uintptr_t)Qnil;
    if (beg < 0) beg += n;
    if (beg < 0 || beg > n) return (uintptr_t)Qnil;
    if (len > n - beg) len = n - beg;
    return (uintptr_t)rb_str_subseq(s, beg, len);
}

struct sprintf_args {
    int argc;
    VALUE *argv;
    VALUE fmt;
};

static VALUE
sprintf_body(VALUE argp)
{
    struct sprintf_args *a = (struct sprintf_args *)argp;
    return rb_str_format(a->argc, a->argv, a->fmt);
}

/* Kernel#format / Kernel#sprintf: rb_str_format itself, the worker rb_f_sprintf calls, skipping only the varargs Kernel dispatch around it -- argument to_s/to_str coercion can re-enter Ruby and a bad format spec raises ArgumentError, so the call runs under rb_protect. */
uintptr_t
rpyyarv_sprintf(int argc, const uintptr_t *argv, uintptr_t fmt, int *state)
{
    VALUE buf[RPYYARV_MAX_ARGC];
    struct sprintf_args a;
    int i;
    *state = 0;
    if (!RB_TYPE_P((VALUE)fmt, T_STRING) || argc < 0 || argc > RPYYARV_MAX_ARGC)
        return (uintptr_t)Qundef;
    for (i = 0; i < argc; i++) buf[i] = (VALUE)argv[i];
    a.argc = argc; a.argv = buf; a.fmt = (VALUE)fmt;
    {
        VALUE ret = rb_protect(sprintf_body, (VALUE)&a, state);
        if (*state) return (uintptr_t)Qnil;
        return (uintptr_t)ret;
    }
}

struct cgi_esc { unsigned char len; char str[6]; };

/* Mirrors ext/cgi/escape/escape.c's html_escape_table exactly: the five characters CGI.escapeHTML replaces. */
static const struct cgi_esc cgi_html_escape_table[UCHAR_MAX + 1] = {
    ['\''] = {5, "&#39;"},
    ['&']  = {5, "&amp;"},
    ['"']  = {6, "&quot;"},
    ['<']  = {4, "&lt;"},
    ['>']  = {4, "&gt;"},
};

/* CGI.escapeHTML for an ascii-compatible-encoded String: ext/cgi/escape/escape.c's optimized_escape_html byte loop, taken only when that C extension itself would take it (rb_enc_str_asciicompat_p); a dummy/non-ascii-compatible encoding falls back to the pure-Ruby CGI::Escape#escapeHTML, which handles it via re-encoding. Neither branch can re-enter Ruby or raise for a String receiver, so no rb_protect. */
uintptr_t
rpyyarv_cgi_escape_html(uintptr_t str)
{
    VALUE s = (VALUE)str, escaped;
    rb_encoding *enc;
    const char *cstr, *end;
    char *buf, *dest;
    long len;
    if (!RB_TYPE_P(s, T_STRING)) return (uintptr_t)Qundef;
    enc = rb_enc_get(s);
    if (!rb_enc_asciicompat(enc)) return (uintptr_t)Qundef;
    len = RSTRING_LEN(s);
    if (len >= LONG_MAX / 6) return (uintptr_t)Qundef;
    buf = ALLOC_N(char, len * 6);
    cstr = RSTRING_PTR(s);
    end = cstr + len;
    dest = buf;
    while (cstr < end) {
        unsigned char c = (unsigned char)*cstr++;
        unsigned char l = cgi_html_escape_table[c].len;
        if (l) {
            memcpy(dest, cgi_html_escape_table[c].str, l);
            dest += l;
        }
        else {
            *dest++ = (char)c;
        }
    }
    if (len < dest - buf) {
        escaped = rb_str_new(buf, dest - buf);
        rb_enc_associate(escaped, enc);
    }
    else {
        escaped = rb_str_dup(s);
    }
    xfree(buf);
    return (uintptr_t)escaped;
}

/* String#match? without rb_protect: taken only when onig_search cannot raise. re.c's rb_reg_prepare_re returns its regexp unchanged, with no recompile or ArgumentError, whenever the string's encoding already equals the compiled pattern's -- the exact-match branch of rb_reg_prepare_enc -- and a broken string is ruled out separately, since that raises before the encoding check runs.
 *
 * The timeout question: re.c keeps a per-Regexp deadline (onigmo.h's regex_t::timelimit, a public struct field) and a process-global fallback (re.c's rb_reg_match_time_limit, which -- unlike the timelimit field -- turned out not to be exported for linking, confirmed by ld at this shim's build time). re.c's own rb_reg_timeout_p *is* exported (regint.h declares it; declared again here rather than pulling in that whole internal onigmo header) and folds both into one end-time on its first call (the *end_time == 0 arm), touching no state and calling no clock when neither is armed; asking it that once, the same way onig_search's periodic callback would, is how this shim learns "no timeout is armed" without the hidden symbol. */
extern bool rb_reg_timeout_p(regex_t *reg, void *end_time);

uintptr_t
rpyyarv_str_match_p_fast(uintptr_t str, uintptr_t re)
{
    VALUE s = (VALUE)str, r = (VALUE)re;
    regex_t *reg;
    rb_hrtime_t end_time = 0;
    if (!RB_TYPE_P(s, T_STRING) || !RB_TYPE_P(r, T_REGEXP))
        return (uintptr_t)Qundef;
    if (rb_enc_str_coderange(s) == ENC_CODERANGE_BROKEN)
        return (uintptr_t)Qundef;
    reg = RREGEXP_PTR(r);
    if (reg->enc != rb_enc_get(s))
        return (uintptr_t)Qundef;
    rb_reg_timeout_p(reg, &end_time);
    if (end_time != RB_HRTIME_MAX)
        return (uintptr_t)Qundef;
    return matchp_search(reg, s, NULL, NULL) == ONIG_MISMATCH
           ? (uintptr_t)Qfalse : (uintptr_t)Qtrue;
}
