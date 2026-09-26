/* The one place the C side tests which CRuby it is compiled against.
   Include after the host's internal headers. Each block names the host
   changes it absorbs; hostconsts.c exports the same values to Python. */
#ifndef RPYYARV_HOST_COMPAT_H
#define RPYYARV_HOST_COMPAT_H

#include <stddef.h>
#include "ruby/version.h"

#define RPYYARV_HOST_VERSION \
    (RUBY_API_VERSION_MAJOR * 100 + RUBY_API_VERSION_MINOR)

/* Where a T_OBJECT or imemo/fields keeps its fields out of line: when
   (flags & RPYYARV_IV_HEAP_MASK) == RPYYARV_IV_HEAP_BITS, the word at
   RObject.as.ary points to them, RPYYARV_IV_HEAP_BASE words in. */
#if RPYYARV_HOST_VERSION >= 401
/* 86951165b8 dropped ROBJECT_HEAP: the shape id's layout bits say it, and
   the out-of-line fields are an imemo/fields object of their own, marked
   by its own shape, so a raw add must not grow only the owner's shape. */
# define RPYYARV_IV_HEAP_MASK \
    (((VALUE)SHAPE_ID_LAYOUT_MASK << SHAPE_FLAG_SHIFT) | RUBY_T_MASK)
# define RPYYARV_IV_HEAP_BITS \
    (((VALUE)SHAPE_ID_LAYOUT_EXTENDED << SHAPE_FLAG_SHIFT) | RUBY_T_OBJECT)
# define RPYYARV_IV_HEAP_BASE \
    (offsetof(struct rb_fields, as.embed.fields) / SIZEOF_VALUE)
# define RPYYARV_IV_HEAP_IS_OBJECT 1
# define RPYYARV_IV_RAW_ADD_P(shape_id) (!rb_shape_extended_p(shape_id))
/* A shape names its parent by offset, and too complex became complex. */
# define RPYYARV_SHAPE_PARENT(shape) ((shape)->parent_offset)
# define rb_shape_too_complex_p rb_shape_complex_p
/* a26f528b3b made every T_DATA an RTypedData and dropped the flag that
   told them apart; 0 makes the flag test vacuous. */
# define RPYYARV_FL_TYPED_DATA 0
#else
# define RPYYARV_IV_HEAP_MASK ROBJECT_HEAP
# define RPYYARV_IV_HEAP_BITS ROBJECT_HEAP
# define RPYYARV_IV_HEAP_BASE 0
# define RPYYARV_IV_HEAP_IS_OBJECT 0
# define RPYYARV_IV_RAW_ADD_P(shape_id) 1
# define RPYYARV_SHAPE_PARENT(shape) ((shape)->parent_id)
# define RPYYARV_FL_TYPED_DATA RUBY_TYPED_FL_IS_TYPED_DATA
#endif

#endif
