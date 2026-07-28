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
