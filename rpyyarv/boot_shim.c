#include <stdlib.h>
#include <ruby.h>

#include "boot_shim.h"

/* Declared in the internal header iseq.h; forward-declared to avoid
   pulling in vm_core.h. */
struct rb_iseq_struct;
VALUE rb_iseqw_new(const struct rb_iseq_struct *iseq);

void *
rpyyarv_boot(int argc, char **argv, int *status_out)
{
    /* Must live on the machine stack: ruby_init_stack records its address
       as the lower bound of the conservative GC scan. */
    VALUE variable_in_this_stack_frame;

    ruby_sysinit(&argc, &argv);
    ruby_init_stack(&variable_in_this_stack_frame);
    ruby_init();

    void *n = ruby_options(argc, argv);

    /* ruby_options returns Qtrue/Qfalse/Fixnum instead of an ISeq for
       --version, --help and syntax errors. */
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

struct funcallv_args {
    VALUE recv;
    ID    mid;
    int   argc;
    const VALUE *argv;
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
    /* On the machine stack, so the conservative scan covers the arguments
       until rb_funcallv has copied them onto the VM stack. */
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
    if (*state) {
        rb_set_errinfo(Qnil);
        return (uintptr_t)Qnil;
    }
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
    /* The wrapper is held only in FFI-side memory, which the GC never
       scans. Pin it (it also marks the wrapped iseq). Boot-once, so the
       permanent registration is fine. */
    rb_gc_register_mark_object(v);
    return (uintptr_t)v;
}

const char *
rpyyarv_cstr(uintptr_t str)
{
    VALUE v = (VALUE)str;
    if (!RB_TYPE_P(v, T_STRING)) return NULL;
    return rb_string_value_cstr(&v);
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

int rpyyarv_is_array(uintptr_t v)  { return RB_TYPE_P((VALUE)v, T_ARRAY) ? 1 : 0; }
int rpyyarv_is_symbol(uintptr_t v) { return SYMBOL_P((VALUE)v) ? 1 : 0; }
int rpyyarv_is_fixnum(uintptr_t v) { return FIXNUM_P((VALUE)v) ? 1 : 0; }
int rpyyarv_is_string(uintptr_t v) { return RB_TYPE_P((VALUE)v, T_STRING) ? 1 : 0; }
int rpyyarv_is_hash(uintptr_t v)   { return RB_TYPE_P((VALUE)v, T_HASH) ? 1 : 0; }
int rpyyarv_is_nil(uintptr_t v)    { return NIL_P((VALUE)v) ? 1 : 0; }
int rpyyarv_is_true(uintptr_t v)   { return (VALUE)v == Qtrue ? 1 : 0; }
int rpyyarv_is_false(uintptr_t v)  { return (VALUE)v == Qfalse ? 1 : 0; }

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
rpyyarv_gc_start(void)
{
    rb_gc_start();
}

uintptr_t
rpyyarv_str_new(const char *s)
{
    return (uintptr_t)rb_str_new_cstr(s);
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
