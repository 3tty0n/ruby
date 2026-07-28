/*
 * Pure-C check that the interception seam exists, independent of RPython.
 *
 * CRuby's main.c is:
 *     RUBY_INIT_STACK; ruby_init();
 *     return ruby_run_node(ruby_options(argc, argv));
 *
 * eval.c:286 shows ruby_options() returns the main script's rb_iseq_t.
 * We take it and never call ruby_run_node, so the script does not run.
 */

#include <stdio.h>
#include <stdlib.h>
#include <ruby.h>

struct rb_iseq_struct;
VALUE rb_iseqw_new(const struct rb_iseq_struct *iseq);

struct probe_args {
    VALUE iseqw;
};

/* rb_funcall may raise, and CRuby raises by longjmp. Without rb_protect the
   jump would fly past this frame. */
static VALUE
probe_body(VALUE argp)
{
    struct probe_args *a = (struct probe_args *)argp;
    VALUE iseqw = a->iseqw;

    printf("[rpyyarv] label         : %s\n",
           RSTRING_PTR(rb_inspect(rb_funcall(iseqw, rb_intern("label"), 0))));
    printf("[rpyyarv] absolute_path : %s\n",
           RSTRING_PTR(rb_inspect(rb_funcall(iseqw, rb_intern("absolute_path"), 0))));

    /* to_a is the input format for loader.py. */
    VALUE ary = rb_funcall(iseqw, rb_intern("to_a"), 0);
    printf("[rpyyarv] to_a.size     : %ld\n", RARRAY_LEN(ary));

    /* Last element is the instruction list: arrays, label symbols and
       line numbers interleaved. */
    VALUE insns = rb_ary_entry(ary, RARRAY_LEN(ary) - 1);
    long n = RARRAY_LEN(insns), n_insn = 0, n_label = 0, n_lineno = 0;
    for (long i = 0; i < n; i++) {
        VALUE e = rb_ary_entry(insns, i);
        if (RB_TYPE_P(e, T_ARRAY)) n_insn++;
        else if (SYMBOL_P(e))      n_label++;
        else if (FIXNUM_P(e))      n_lineno++;
    }
    printf("[rpyyarv] elements: %ld (insn %ld / label %ld / lineno %ld)\n",
           n, n_insn, n_label, n_lineno);

    for (long i = 0, shown = 0; i < n && shown < 6; i++) {
        VALUE e = rb_ary_entry(insns, i);
        if (!RB_TYPE_P(e, T_ARRAY)) continue;
        printf("[rpyyarv]   %.100s\n", RSTRING_PTR(rb_inspect(e)));
        shown++;
    }

    VALUE dis = rb_funcall(iseqw, rb_intern("disasm"), 0);
    VALUE lines = rb_str_split(dis, "\n");
    printf("[rpyyarv] --- disasm (first 8 lines) ---\n");
    for (long i = 0; i < RARRAY_LEN(lines) && i < 8; i++) {
        printf("[rpyyarv]   %s\n", RSTRING_PTR(rb_ary_entry(lines, i)));
    }

    return Qnil;
}

static int
rpyyarv_main(int argc, char **argv)
{
    RUBY_INIT_STACK;
    ruby_init();

    void *n = ruby_options(argc, argv);

    int status = 0;
    if (!ruby_executable_node(n, &status)) {
        fprintf(stderr, "[rpyyarv] no executable node (status=%d)\n", status);
        return ruby_cleanup(status);
    }

    VALUE iseqw = rb_iseqw_new((const struct rb_iseq_struct *)n);
    printf("[rpyyarv] === Success: intercepted main ISeq ===\n");

    struct probe_args a = { iseqw };
    int state = 0;
    rb_protect(probe_body, (VALUE)&a, &state);
    if (state) {
        fprintf(stderr, "[rpyyarv] exception during probe\n");
        rb_set_errinfo(Qnil);
    }

    printf("[rpyyarv] ruby_run_node() was never called.\n");
    return ruby_cleanup(0);
}

int
main(int argc, char **argv)
{
    ruby_sysinit(&argc, &argv);
    return ruby_start_main(rpyyarv_main, argc, argv);
}
