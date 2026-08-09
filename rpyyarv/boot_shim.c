#include <stdlib.h>
#include <stddef.h>
#include <ruby.h>

/* In-tree, so the object-shape API libruby does not export is still reachable. */
#include "shape.h"
#include "internal/array.h"
/* Its STATIC_ASSERTs are what let the RPython ivar fast path read an imemo/fields with the RObject layout. */
#include "internal/imemo.h"
#include "internal/numeric.h"
#include "internal/range.h"
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

void *
rpyyarv_boot(int argc, char **argv, int *status_out)
{
    /* On the machine stack: ruby_init_stack records its address as the lower bound of the conservative GC scan. */
    VALUE variable_in_this_stack_frame;

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

static VALUE
block_yielder(RB_BLOCK_CALL_FUNC_ARGLIST(yielded, callback_arg))
{
    /* On the machine stack, so the yielded values stay scannable until the RPython side copies them into a frame the mark hook reaches. */
    VALUE buf[RPYYARV_MAX_ARGC];
    int i, n = argc;
    VALUE r;

    (void)yielded;
    (void)blockarg;
    if (!block_callback) return Qnil;
    if (n < 0) n = 0;
    if (n > RPYYARV_MAX_ARGC) n = RPYYARV_MAX_ARGC;
    for (i = 0; i < n; i++) buf[i] = argv[i];
    r = (VALUE)block_callback((long)FIX2LONG(callback_arg), n,
                              (uintptr_t *)buf);
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
};

static VALUE
call_with_block_body(VALUE argp)
{
    struct blockcall_args *a = (struct blockcall_args *)argp;
    return rb_block_call(a->recv, a->mid, a->argc, a->argv, block_yielder,
                         LONG2FIX(a->handle));
}

uintptr_t
rpyyarv_call_with_block(uintptr_t recv, uintptr_t mid, int argc,
                        const uintptr_t *argv, long handle, int *state)
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
    int status = RPYYARV_TRAMP_OK;
    VALUE err = Qnil;
    VALUE r;

    if (!tramp_callback) {
        rb_raise(rb_eRuntimeError, "rpyyarv: no trampoline callback");
    }
    r = (VALUE)tramp_callback((uintptr_t)self, (uintptr_t)mid, argc,
                              (uintptr_t *)argv, (uintptr_t)blockproc,
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
    /* An ifunc Proc: calling it reaches block_yielder with the same LONG2FIX'd handle rb_block_call passes. */
    return rb_proc_new(block_yielder, handle);
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
    tmp = rb_check_array_type(p->ary);
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
rpyyarv_bop_mask(void)
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
#undef BOP

    return (uintptr_t)i << RPYYARV_BOP_COUNT_SHIFT | mask;
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
    rb_provide(RSTRING_PTR(rb_get_path((VALUE)argp)));
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
