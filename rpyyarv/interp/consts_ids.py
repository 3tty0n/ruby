"""Interned method-id symbols, in original interning order."""
from __future__ import absolute_import

import os

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import dispatch
from rpyyarv import gcroots
from rpyyarv import helpers
from rpyyarv import insns
from rpyyarv import optable
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RPyYarvError, RubyException, UnsupportedOperation
from rpyyarv.frame import (Frame, PENDING_BREAK, PENDING_NEXT, PENDING_NONE,
                   PENDING_RAISE, PENDING_RETRY, PENDING_RETURN)
from rpyyarv.iseq import (CATCH_ENSURE, CATCH_RESCUE, CATCH_RETRY,
                          NO_BLOCK_ISEQ, W_CallInfo)
from rpyyarv.rlib import (JitDriver, StackOverflow, always_inline, check_stack_overflow,
                  dont_look_inside, on_foreign_stack, promote, raw_word, set_user_param,
                  unchecked_stack_start, unchecked_stack_stop, unroll_safe)

TO_S = symbols.intern('to_s')


DUP = symbols.intern('dup')


EVAL = symbols.intern('eval')


# The empty leading segment the loader puts in a `::Foo` constant path.
ROOT_CBASE = symbols.intern('')


NEW = symbols.intern('new')


INITIALIZE = symbols.intern('initialize')


BLOCK_GIVEN = symbols.intern('block_given?')


DIR_UNDERSCORE = symbols.intern('__dir__')


BACKTRACE_PRIM = symbols.intern('__rpyyarv_backtrace__')


HASH_PAIRS_PRIM = symbols.intern('__rpyyarv_hash_pairs__')


REQUIRE_PRIM = symbols.intern('__rpyyarv_require__')


METHOD_UNDERSCORE = symbols.intern('__method__')


CALLEE_UNDERSCORE = symbols.intern('__callee__')


ITSELF = symbols.intern('itself')


REVERSE_EACH = symbols.intern('reverse_each')


EACH_SLICE = symbols.intern('each_slice')


EACH_WITH_INDEX = symbols.intern('each_with_index')


STEP = symbols.intern('step')


INDEX = symbols.intern('index')


SUCC = symbols.intern('succ')


BUFFER = symbols.intern('buffer')


GETBYTE = symbols.intern('getbyte')


SETBYTE = symbols.intern('setbyte')


ALLOCATE = symbols.intern('allocate')


FORCE_ENCODING = symbols.intern('force_encoding')


UNPACK1 = symbols.intern('unpack1')


OFFSET = symbols.intern('offset')


ATTR_READER = symbols.intern('attr_reader')


ATTR_WRITER = symbols.intern('attr_writer')


ATTR_ACCESSOR = symbols.intern('attr_accessor')


DEFINE_METHOD = symbols.intern('define_method')


SEND = symbols.intern('send')


SEND2 = symbols.intern('__send__')


# opt_regexpmatch2 falls through to this send; CRuby sets $~ there.
MATCH = symbols.intern('=~')


COMPILE = symbols.intern('compile')


METHOD_MISSING = symbols.intern('method_missing')


RUBY2_KEYWORDS = symbols.intern('ruby2_keywords')


# alias/undef compile to a send of one of these (vm.c); registry must see.
CORE_ALIAS = symbols.intern('core#set_method_alias')


CORE_UNDEF = symbols.intern('core#undef_method')


CORE_GVAR_ALIAS = symbols.intern('core#set_variable_alias')


# Literal keywords beside a **, and bare super forwarding (vm.c:4261).
HASH_MERGE_PTR = symbols.intern('core#hash_merge_ptr')


HASH_MERGE_KWD = symbols.intern('core#hash_merge_kwd')


MODULE_FUNCTION = symbols.intern('module_function')


PRIVATE_CLASS_METHOD = symbols.intern('private_class_method')


PRIVATE = symbols.intern('private')


PUBLIC = symbols.intern('public')


REMOVE_METHOD = symbols.intern('remove_method')


UNDEF_METHOD = symbols.intern('undef_method')


ALIAS_METHOD = symbols.intern('alias_method')


INSTANCE_EVAL = symbols.intern('instance_eval')


INSTANCE_EXEC = symbols.intern('instance_exec')


CLASS_EVAL = symbols.intern('class_eval')


MODULE_EVAL = symbols.intern('module_eval')


CORE_LAMBDA = symbols.intern('lambda')


KERNEL_PROC = symbols.intern('proc')


ENC_FIND = symbols.intern('find')


# CGI is absent at install(); const_at's version-keyed cache is memo enough.
CGI_CONST = symbols.intern('CGI')


TO_PROC = symbols.intern('to_proc')


CALL = symbols.intern('call')


YIELD = symbols.intern('yield')


AREF = symbols.intern('[]')


EQQ_ = symbols.intern('===')


SLICE = symbols.intern('slice')


ARITY = symbols.intern('arity')


LAMBDA_P = symbols.intern('lambda?')


EQQ = symbols.intern('===')
