import os
import sys

from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.translator.tool.cbuild import ExternalCompilationInfo

from rpyyarv import symbols
from rpyyarv.error import RubyException

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOP = os.path.dirname(_HERE)
_BUILD = os.environ.get('RPYYARV_BUILD', os.path.join(_TOP, 'build'))


def _arch_include_dir():
    base = os.path.join(_BUILD, '.ext', 'include')
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            cand = os.path.join(base, name)
            if os.path.exists(os.path.join(cand, 'ruby', 'config.h')):
                return cand
    raise RuntimeError(
        '%s not found. Build CRuby with --enable-shared first:\n'
        '    mkdir build && cd build\n'
        '    ../configure --enable-shared --disable-install-doc && make -j'
        % base)


# The arch name, not a path: which one the extensions were built for is fixed by the libruby this binary links against.
_ARCH = os.path.basename(_arch_include_dir())


def _libruby_name():
    for name in sorted(os.listdir(_BUILD)):
        for ext in ('.dylib', '.so'):
            if name.startswith('libruby.') and name.endswith(ext):
                if 'static' in name:
                    continue
                return name[len('lib'):-len(ext)]
    raise RuntimeError('no libruby shared library in %s' % _BUILD)


def _link_extra():
    flags = ['-Wl,-rpath,' + _BUILD]
    if sys.platform == 'darwin':
        # ld bakes in libruby's install prefix; `make relink` rewrites it after
        flags.append('-Wl,-headerpad_max_install_names')
    return flags


eci = ExternalCompilationInfo(
    includes=['ruby.h', 'boot_shim.h'],
    # _TOP and _BUILD carry shape.h and the generated id.h it pulls in.
    include_dirs=[os.path.join(_TOP, 'include'), _arch_include_dir(), _HERE,
                  _TOP, _BUILD],
    separate_module_files=[os.path.join(_HERE, 'boot_shim.c')],
    libraries=[_libruby_name()],
    library_dirs=[_BUILD],
    link_extra=_link_extra(),
)

# VALUE is uintptr_t. Only VALUEs cross this boundary
VALUE = rffi.UINTPTR_T
VALUEP = rffi.CArrayPtr(VALUE)
INTP = rffi.INTP
VOIDP = rffi.VOIDP
MARK_HOOK = lltype.Ptr(lltype.FuncType([], lltype.Void))
CONST_HOOK = lltype.Ptr(lltype.FuncType([], lltype.Void))
BLOCK_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed, rffi.INT, VALUEP,
                                         VALUE], VALUE))
# (self, mid, argc, argv, blockproc, kw, status, errval) -> result
TRAMP_HOOK = lltype.Ptr(lltype.FuncType(
    [VALUE, VALUE, rffi.INT, VALUEP, VALUE, rffi.INT, INTP, VALUEP], VALUE))

# Mirrors RPYYARV_MAX_ARGC; a splat can expand past the old 32 (fileutils passes 47).
MAX_ARGC = 256


def _ext(name, args, result, reenters=False):
    # releasegil=False: all calls hold the GVL; reenters=True on any call that can allocate, so a GC in a callback cannot move objects out from under C locals.
    return rffi.llexternal(name, args, result, compilation_info=eci,
                           releasegil=False,
                           random_effects_on_gcobjs=reenters)


rb_boot = _ext('rpyyarv_boot', [rffi.INT, rffi.CCHARPP, INTP], VOIDP)
rb_cleanup = _ext('rpyyarv_cleanup', [rffi.INT], rffi.INT)
rb_run_node = _ext('rpyyarv_run_node', [VOIDP], rffi.INT, reenters=True)
rb_iseqw_new = _ext('rpyyarv_iseqw_new', [VOIDP], VALUE)
rb_call0 = _ext('rpyyarv_call0', [VALUE, rffi.CCHARP, INTP], VALUE, reenters=True)
rb_str_len = _ext('rpyyarv_str_len', [VALUE], rffi.LONG)
rb_str_ptr = _ext('rpyyarv_str_ptr', [VALUE], rffi.CCHARP)
rb_inspect_cstr = _ext('rpyyarv_inspect_cstr', [VALUE], rffi.CCHARP, reenters=True)
rb_ary_len = _ext('rpyyarv_ary_len', [VALUE], rffi.LONG)
rb_ary_entry = _ext('rpyyarv_ary_entry', [VALUE, rffi.LONG], VALUE, reenters=True)
rb_ary_subseq = _ext('rpyyarv_ary_subseq', [VALUE, rffi.LONG, rffi.LONG],
                     VALUE, reenters=True)
rb_is_array = _ext('rpyyarv_is_array', [VALUE], rffi.INT)
rb_patch_method_equality = _ext('rpyyarv_patch_method_equality', [], lltype.Void,
                                reenters=True)
rb_is_symbol = _ext('rpyyarv_is_symbol', [VALUE], rffi.INT)
rb_is_fixnum = _ext('rpyyarv_is_fixnum', [VALUE], rffi.INT)
rb_is_string = _ext('rpyyarv_is_string', [VALUE], rffi.INT)
rb_is_hash = _ext('rpyyarv_is_hash', [VALUE], rffi.INT)
rb_is_nil = _ext('rpyyarv_is_nil', [VALUE], rffi.INT)
rb_is_true = _ext('rpyyarv_is_true', [VALUE], rffi.INT)
rb_is_false = _ext('rpyyarv_is_false', [VALUE], rffi.INT)
rb_num2long = _ext('rpyyarv_num2long', [VALUE], rffi.LONG, reenters=True)
rb_hash_aref = _ext('rpyyarv_hash_aref', [VALUE, rffi.CCHARP], VALUE, reenters=True)
rb_sym_cstr = _ext('rpyyarv_sym_cstr', [VALUE], rffi.CCHARP, reenters=True)
# No reenters: the codewriter rejects it inside an elidable; safe -- neither this nor rb_shape_iv_index allocates, and elidable calls never survive into an optimized trace.
rb_intern_ = _ext('rpyyarv_intern', [rffi.CCHARP], VALUE)
rb_sym_new = _ext('rpyyarv_sym_new', [rffi.CCHARP], VALUE, reenters=True)
rb_getspecial = _ext('rpyyarv_getspecial', [rffi.INT, INTP], VALUE,
                     reenters=True)
rb_str_intern = _ext('rpyyarv_str_intern', [VALUE, INTP], VALUE,
                     reenters=True)
rb_toregexp = _ext('rpyyarv_toregexp',
                   [rffi.INT, rffi.INT, VALUEP, INTP], VALUE,
                   reenters=True)
rb_funcallv_id = _ext('rpyyarv_funcallv_id',
                      [VALUE, VALUE, rffi.INT, VALUEP, INTP], VALUE, reenters=True)
rb_funcallv_public_id = _ext('rpyyarv_funcallv_public_id',
                             [VALUE, VALUE, rffi.INT, VALUEP, INTP], VALUE,
                             reenters=True)
rb_funcallv_kw_id = _ext('rpyyarv_funcallv_kw_id',
                         [VALUE, VALUE, rffi.INT, VALUEP, rffi.INT, INTP],
                         VALUE, reenters=True)
rb_top_self = _ext('rpyyarv_top_self', [], VALUE)
rb_int2inum = _ext('rpyyarv_int2inum', [rffi.LONG], VALUE, reenters=True)
rb_float_new = _ext('rpyyarv_float_new', [rffi.DOUBLE], VALUE, reenters=True)
rb_float_layout = _ext('rpyyarv_float_layout', [INTP], lltype.Void)
rb_str_new = _ext('rpyyarv_str_new', [rffi.CCHARP, rffi.LONG], VALUE,
                  reenters=True)
rb_ary_new = _ext('rpyyarv_ary_new', [rffi.INT, VALUEP], VALUE, reenters=True)
rb_str_concat = _ext('rpyyarv_str_concat', [rffi.INT, VALUEP], VALUE, reenters=True)
rb_special_consts = _ext('rpyyarv_special_consts',
                         [VALUEP, VALUEP, VALUEP, VALUEP], lltype.Void)
rb_gc_set_mark_hook = _ext('rpyyarv_gc_set_mark_hook', [MARK_HOOK],
                           lltype.Void)
rb_gc_mark_value = _ext('rpyyarv_gc_mark_value', [VALUE], lltype.Void)
rb_gc_mark_maybe = _ext('rpyyarv_gc_mark_maybe', [VALUE], lltype.Void)
rb_set_const_hook = _ext('rpyyarv_set_const_hook', [CONST_HOOK], lltype.Void)
HANDLE_MARK_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed], lltype.Void))
rb_set_handle_mark = _ext('rpyyarv_set_handle_mark_callback',
                          [HANDLE_MARK_HOOK], lltype.Void)
FIBER_SAVE_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed], VOIDP))
FIBER_ARRIVE_HOOK = lltype.Ptr(lltype.FuncType(
    [lltype.Signed, lltype.Signed, lltype.Signed], VOIDP))
FIBER_BORN_HOOK = lltype.Ptr(lltype.FuncType(
    [lltype.Signed, lltype.Signed, lltype.Signed], lltype.Void))
FIBER_KEY_HOOK = lltype.Ptr(lltype.FuncType([lltype.Signed], lltype.Void))
rb_fiber_killed_value = _ext('rpyyarv_fiber_killed_value', [], VALUE)
rb_rethrow_if_fiber_kill = _ext('rpyyarv_rethrow_if_fiber_kill', [VALUE],
                                rffi.INT)
rb_set_fiber_hooks = _ext('rpyyarv_set_fiber_hooks',
                          [FIBER_SAVE_HOOK, FIBER_ARRIVE_HOOK, FIBER_BORN_HOOK,
                           FIBER_KEY_HOOK, VOIDP, VOIDP], lltype.Void)
rb_set_method_hook = _ext('rpyyarv_set_method_hook', [CONST_HOOK], lltype.Void)
rb_gc_start = _ext('rpyyarv_gc_start', [], lltype.Void, reenters=True)
rb_core_classes = _ext('rpyyarv_core_classes', [VALUEP], lltype.Void)
rb_define_class_ = _ext('rpyyarv_define_class',
                        [VALUE, VALUE, VALUE, INTP], VALUE, reenters=True)
rb_define_module_ = _ext('rpyyarv_define_module',
                         [VALUE, VALUE, INTP], VALUE, reenters=True)
rb_class_superclass = _ext('rpyyarv_class_superclass', [VALUE, INTP], VALUE, reenters=True)
rb_singleton_class = _ext('rpyyarv_singleton_class', [VALUE, INTP], VALUE, reenters=True)
rb_obj_alloc = _ext('rpyyarv_obj_alloc', [VALUE, INTP], VALUE, reenters=True)
rb_obj_alloc_fast = _ext('rpyyarv_obj_alloc_fast', [VALUE], VALUE, reenters=True)
rb_alloc_default = _ext('rpyyarv_alloc_default', [VALUE], VALUE, reenters=True)
rb_const_get_ = _ext('rpyyarv_const_get', [VALUE, VALUE, INTP], VALUE, reenters=True)
rb_const_at_ = _ext('rpyyarv_const_at', [VALUE, VALUE, INTP], VALUE,
                    reenters=True)
rb_const_set_ = _ext('rpyyarv_const_set', [VALUE, VALUE, VALUE, INTP],
                     lltype.Void, reenters=True)
rb_ivar_get_ = _ext('rpyyarv_ivar_get', [VALUE, VALUE, INTP], VALUE, reenters=True)
rb_ivar_set_ = _ext('rpyyarv_ivar_set', [VALUE, VALUE, VALUE, INTP],
                    lltype.Void, reenters=True)
rb_shape_iv_index = _ext('rpyyarv_shape_iv_index',   # no reenters: see rb_intern_
                         [rffi.UINT, VALUE, INTP], rffi.INT)
rb_shape_add_ivar_fits = _ext('rpyyarv_shape_add_ivar_fits',  # no reenters: see rb_intern_
                              [rffi.UINT, rffi.UINT, VALUE, INTP], rffi.INT)
rb_object_layout = _ext('rpyyarv_object_layout', [INTP], lltype.Void)
rb_set_block_callback = _ext('rpyyarv_set_block_callback', [BLOCK_HOOK],
                             lltype.Void)
rb_call_with_block = _ext('rpyyarv_call_with_block',
                          [VALUE, VALUE, rffi.INT, VALUEP, rffi.LONG,
                           rffi.INT, INTP], VALUE, reenters=True)
rb_call_with_proc = _ext('rpyyarv_call_with_proc',
                         [VALUE, VALUE, rffi.INT, VALUEP, VALUE,
                          rffi.INT, INTP], VALUE, reenters=True)
rb_set_trampoline_callback = _ext('rpyyarv_set_trampoline_callback',
                                  [TRAMP_HOOK], lltype.Void)
rb_define_method_id = _ext('rpyyarv_define_method',
                           [VALUE, VALUE, rffi.INT, INTP], lltype.Void,
                           reenters=True)
rb_array_layout = _ext('rpyyarv_array_layout', [INTP], lltype.Void)
# No reenters: rb_str_eql_internal neither allocates nor raises, see rb_range_part.
rb_str_eq = _ext('rpyyarv_str_eq', [VALUE, VALUE], VALUE)
rb_ary_resurrect = _ext('rpyyarv_ary_resurrect', [VALUE, INTP], VALUE, reenters=True)
rb_ary_store_ = _ext('rpyyarv_ary_store', [VALUE, rffi.LONG, VALUE, INTP],
                     lltype.Void, reenters=True)
rb_ary_new_capa = _ext('rpyyarv_ary_new_capa', [rffi.LONG, INTP], VALUE, reenters=True)
rb_ary_store_fresh = _ext('rpyyarv_ary_store_fresh', [VALUE, rffi.LONG, VALUE],
                          lltype.Void, reenters=True)
rb_ary_new_capa_fast = _ext('rpyyarv_ary_new_capa_fast', [rffi.LONG], VALUE, reenters=True)
rb_ary_new_filled_fast = _ext('rpyyarv_ary_new_filled_fast', [rffi.LONG, VALUE],
                              VALUE, reenters=True)
rb_ary_new_filled = _ext('rpyyarv_ary_new_filled', [rffi.LONG, VALUE, INTP],
                         VALUE, reenters=True)
rb_ary_cat = _ext('rpyyarv_ary_cat', [VALUE, rffi.INT, VALUEP, INTP],
                  lltype.Void, reenters=True)
rb_range_new_ = _ext('rpyyarv_range_new', [VALUE, VALUE, rffi.INT, INTP],
                     VALUE, reenters=True)
rb_gvar_get_ = _ext('rpyyarv_gvar_get', [rffi.CCHARP, INTP], VALUE, reenters=True)
rb_gvar_set_ = _ext('rpyyarv_gvar_set', [rffi.CCHARP, VALUE, INTP],
                    lltype.Void, reenters=True)
rb_proc_new = _ext('rpyyarv_proc_new', [rffi.LONG, INTP], VALUE, reenters=True)
rb_pop_dead_handle = _ext('rpyyarv_pop_dead_handle', [], rffi.LONG)
rb_is_proc = _ext('rpyyarv_is_proc', [VALUE], rffi.INT)
rb_is_class = _ext('rpyyarv_is_class', [VALUE], rffi.INT)
rb_gc_register = _ext('rpyyarv_gc_register_mark_object', [VALUE], lltype.Void, reenters=True)
rb_take_errinfo = _ext('rpyyarv_take_errinfo', [], VALUE)
rb_swap_errinfo = _ext('rpyyarv_swap_errinfo', [VALUE], VALUE)
rb_obj_is_kind_of = _ext('rpyyarv_obj_is_kind_of', [VALUE, VALUE, INTP],
                         rffi.INT, reenters=True)
rb_cleanup_with_error = _ext('rpyyarv_cleanup_with_error', [VALUE], rffi.INT,
                             reenters=True)
rb_hash_new_capa = _ext('rpyyarv_hash_new_capa', [rffi.LONG, INTP], VALUE, reenters=True)
rb_hash_aset_ = _ext('rpyyarv_hash_aset', [VALUE, VALUE, VALUE, INTP],
                     lltype.Void, reenters=True)
rb_hash_resurrect = _ext('rpyyarv_hash_resurrect', [VALUE, INTP], VALUE, reenters=True)
rb_hash_size = _ext('rpyyarv_hash_size', [VALUE], rffi.LONG)
rb_hash_lookup = _ext('rpyyarv_hash_lookup', [VALUE, VALUE, INTP], VALUE, reenters=True)
rb_hash_aref_full = _ext('rpyyarv_hash_aref_v', [VALUE, VALUE, INTP], VALUE,
                         reenters=True)
rb_set_include = _ext('rpyyarv_set_include', [VALUE, VALUE, INTP], VALUE,
                      reenters=True)
rb_hash_pairs = _ext('rpyyarv_hash_pairs', [VALUE, INTP], VALUE,
                     reenters=True)
rb_alias_variable = _ext('rpyyarv_alias_variable', [VALUE, VALUE, INTP],
                         VALUE, reenters=True)
rb_hash_lookup_fast = _ext('rpyyarv_hash_lookup_fast', [VALUE, VALUE], VALUE)
rb_hash_aset_fast = _ext('rpyyarv_hash_aset_fast', [VALUE, VALUE, VALUE],
                         VALUE)
rb_str_push = _ext('rpyyarv_str_push', [VALUE, VALUE, INTP], VALUE,
                   reenters=True)
rb_str_start_with = _ext('rpyyarv_str_start_with', [VALUE, VALUE], VALUE)
rb_int_to_s_fast = _ext('rpyyarv_int_to_s', [VALUE], VALUE)
rb_str_gsub2 = _ext('rpyyarv_str_gsub2', [VALUE, VALUE, VALUE, VALUE, INTP],
                    VALUE, reenters=True)
rb_str_casecmp_fast = _ext('rpyyarv_str_casecmp', [VALUE, VALUE], VALUE)
rb_str_cmp_fast = _ext('rpyyarv_str_cmp', [VALUE, VALUE], VALUE)
rb_str_downcase_fast = _ext('rpyyarv_str_downcase', [VALUE], VALUE)
rb_str_downcase_bang = _ext('rpyyarv_str_downcase_bang', [VALUE], VALUE)
rb_str_upcase_fast = _ext('rpyyarv_str_upcase', [VALUE], VALUE)
rb_str_upcase_bang = _ext('rpyyarv_str_upcase_bang', [VALUE], VALUE)
rb_sym_to_s_fast = _ext('rpyyarv_sym_to_s', [VALUE], VALUE)
rb_str_dup_fast = _ext('rpyyarv_str_dup', [VALUE], VALUE)
rb_str_length_fast = _ext('rpyyarv_str_length', [VALUE], VALUE)
rb_str_tr1 = _ext('rpyyarv_str_tr1', [VALUE, VALUE, VALUE], VALUE)
rb_str_index_of = _ext('rpyyarv_str_index_of', [VALUE, VALUE], VALUE)
rb_str_match_p = _ext('rpyyarv_str_match_p', [VALUE, VALUE, INTP], VALUE,
                      reenters=True)
rb_str_eq_tilde = _ext('rpyyarv_str_eq_tilde', [VALUE, VALUE, INTP], VALUE,
                       reenters=True)
rb_reg_eqq_fast = _ext('rpyyarv_reg_eqq', [VALUE, VALUE, INTP], VALUE,
                       reenters=True)
rb_last_match0 = _ext('rpyyarv_last_match0', [], VALUE)
rb_last_match1 = _ext('rpyyarv_last_match1', [VALUE], VALUE)
rb_str_match_fast = _ext('rpyyarv_str_match', [VALUE, VALUE, INTP], VALUE,
                         reenters=True)
rb_str_empty_p = _ext('rpyyarv_str_empty_p', [VALUE], VALUE)
rb_hash_empty_p = _ext('rpyyarv_hash_empty_p', [VALUE], VALUE)
rb_str_uminus = _ext('rpyyarv_str_uminus', [VALUE], VALUE)
rb_ary_pop_fast = _ext('rpyyarv_ary_pop_fast', [VALUE], VALUE)
rb_ary_push1 = _ext('rpyyarv_ary_push1', [VALUE, VALUE], VALUE)
rb_ary_shift_fast = _ext('rpyyarv_ary_shift_fast', [VALUE], VALUE)
rb_ary_unshift1 = _ext('rpyyarv_ary_unshift1', [VALUE, VALUE], VALUE)
rb_ary_hash_freeze = _ext('rpyyarv_ary_hash_freeze', [VALUE], VALUE)
rb_hash_keys_fast = _ext('rpyyarv_hash_keys_fast', [VALUE, INTP], VALUE,
                         reenters=True)
rb_ary_flatten_bang1 = _ext('rpyyarv_ary_flatten_bang1', [VALUE], VALUE)
rb_ss_pos = _ext('rpyyarv_ss_pos', [VALUE], VALUE)
rb_ss_set_pos = _ext('rpyyarv_ss_set_pos', [VALUE, VALUE], VALUE)
rb_ss_eos_p = _ext('rpyyarv_ss_eos_p', [VALUE], VALUE)
rb_ss_matched_size = _ext('rpyyarv_ss_matched_size', [VALUE], VALUE)
rb_ss_skip = _ext('rpyyarv_ss_skip', [VALUE, VALUE, INTP], VALUE,
                  reenters=True)
rb_str_byteslice2 = _ext('rpyyarv_str_byteslice2', [VALUE, VALUE, VALUE],
                         VALUE)
rb_str_force_encoding_fast = _ext('rpyyarv_str_force_encoding_fast',
                                  [VALUE, VALUE], VALUE, reenters=True)
rb_unpack1_double = _ext('rpyyarv_unpack1_double', [VALUE, VALUE, VALUE],
                         VALUE, reenters=True)
# No reenters: scans and caches a coderange in the flags, allocating nothing.
rb_str_ascii_only_p = _ext('rpyyarv_str_ascii_only_p', [VALUE], VALUE)
rb_pack_double_into = _ext('rpyyarv_pack_double_into', [VALUE, VALUE, VALUE],
                           VALUE, reenters=True)
rb_sprintf_ = _ext('rpyyarv_sprintf', [rffi.INT, VALUEP, VALUE, INTP], VALUE,
                   reenters=True)
rb_cgi_escape_html = _ext('rpyyarv_cgi_escape_html', [VALUE], VALUE)
rb_str_match_p_fast = _ext('rpyyarv_str_match_p_fast', [VALUE, VALUE], VALUE)
rb_hash_delete = _ext('rpyyarv_hash_delete', [VALUE, VALUE, INTP],
                      lltype.Void, reenters=True)
rb_hash_keys = _ext('rpyyarv_hash_keys', [VALUE, INTP], VALUE, reenters=True)
rb_to_hash_type = _ext('rpyyarv_to_hash_type', [VALUE, INTP], VALUE, reenters=True)
rb_splat_array = _ext('rpyyarv_splat_array', [VALUE, rffi.INT, INTP], VALUE, reenters=True)
rb_concat_array = _ext('rpyyarv_concat_array', [VALUE, VALUE, rffi.INT, INTP], VALUE, reenters=True)
rb_vm_core = _ext('rpyyarv_vm_core', [], VALUE, reenters=True)
rb_arity_error = _ext('rpyyarv_arity_error',
                      [rffi.INT, rffi.INT, rffi.INT, INTP], VALUE,
                      reenters=True)
rb_keyword_error = _ext('rpyyarv_keyword_error',
                        [rffi.CCHARP, VALUE, INTP], VALUE, reenters=True)
rb_local_jump_error = _ext('rpyyarv_local_jump_error',
                           [rffi.CCHARP, VALUE, rffi.INT, INTP], VALUE,
                           reenters=True)
rb_set_block_unwind = _ext('rpyyarv_set_block_unwind', [], lltype.Void)
rb_bop_mask = _ext('rpyyarv_bop_mask', [INTP], VALUE, reenters=True)
rb_require_resolve = _ext('rpyyarv_require_resolve', [VALUE, VALUEP, INTP],
                          rffi.INT, reenters=True)
rb_provide_ = _ext('rpyyarv_provide', [VALUE, INTP], lltype.Void,
                   reenters=True)
rb_absolute_path = _ext('rpyyarv_absolute_path', [VALUE, VALUE, INTP], VALUE,
                        reenters=True)
rb_method_owner = _ext('rpyyarv_method_owner', [VALUE, VALUE], VALUE,
                       reenters=True)
rb_super_owner = _ext('rpyyarv_super_owner', [VALUE, VALUE, VALUE], VALUE,
                      reenters=True)
rb_responds = _ext('rpyyarv_responds', [VALUE, VALUE], rffi.INT,
                   reenters=True)
rb_class_le = _ext('rpyyarv_class_le', [VALUE, VALUE], rffi.INT,
                   reenters=True)
rb_ary_to_ary = _ext('rpyyarv_ary_to_ary', [VALUE, INTP], VALUE,
                     reenters=True)
rb_sym_name = _ext('rpyyarv_sym_name', [VALUE], VALUE, reenters=True)
rb_current_receiver = _ext('rpyyarv_current_receiver', [], VALUE,
                           reenters=True)
rb_dir_of = _ext('rpyyarv_dir_of', [VALUE], VALUE, reenters=True)
rb_cvar_get = _ext('rpyyarv_cvar_get', [VALUE, VALUE, INTP], VALUE,
                   reenters=True)
rb_cvar_set = _ext('rpyyarv_cvar_set', [VALUE, VALUE, VALUE, INTP],
                   lltype.Void, reenters=True)
rb_cvar_defined = _ext('rpyyarv_cvar_defined', [VALUE, VALUE], rffi.INT,
                       reenters=True)
rb_is_singleton_class = _ext('rpyyarv_is_singleton_class', [VALUE], rffi.INT,
                             reenters=True)
# No reenters: reads two struct fields after a type test, allocating nothing.
rb_range_part = _ext('rpyyarv_range_part', [VALUE, rffi.INT], VALUE)
rb_struct_member_index = _ext('rpyyarv_struct_member_index',
                              [VALUE, VALUE], rffi.INT, reenters=True)
rb_struct_get = _ext('rpyyarv_struct_get', [VALUE, rffi.INT], VALUE)
rb_struct_set = _ext('rpyyarv_struct_set', [VALUE, rffi.INT, VALUE],
                     lltype.Void)
rb_class_ivar_get = _ext('rpyyarv_class_ivar_get', [VALUE, VALUE], VALUE)
rb_ivar_defined = _ext('rpyyarv_ivar_defined', [VALUE, VALUE], rffi.INT)
rb_const_defined = _ext('rpyyarv_const_defined',
                        [VALUE, VALUE, rffi.INT], rffi.INT)
rb_method_defined = _ext('rpyyarv_method_defined',
                         [VALUE, VALUE, rffi.INT], rffi.INT, reenters=True)
rb_str_getbyte = _ext('rpyyarv_str_getbyte', [VALUE, VALUE], VALUE)
rb_str_setbyte = _ext('rpyyarv_str_setbyte', [VALUE, VALUE, VALUE], VALUE,
                      reenters=True)
rb_str_append = _ext('rpyyarv_str_append', [VALUE, VALUE], VALUE,
                     reenters=True)
rb_call_super = _ext('rpyyarv_call_super',
                     [VALUE, VALUE, VALUE, VALUE, rffi.INT, VALUEP,
                      rffi.INT, VALUE, INTP],
                     VALUE, reenters=True)
# No reenters: the barrier sets bits in preallocated page bitmaps and reaches no mark callback; see the comment on rpyyarv_obj_written.
rb_obj_written = _ext('rpyyarv_obj_written', [VALUE, VALUE], lltype.Void)
rb_wb_direct = _ext('rpyyarv_wb_direct', [], rffi.INT)

REQ_LOADED = 0
REQ_RB = 1
REQ_FOREIGN = 2

NCLASS = 14


def _v(n):
    return rffi.cast(VALUE, n)


# One preallocated cell per shim nesting level; a CRuby call can trampoline back into RPyYARV, so these really do nest.
SHIM_DEPTH = 64

_status_pool = lltype.malloc(INTP.TO, SHIM_DEPTH, flavor='raw',
                             immortal=True, zero=True)
_argv_pool = lltype.malloc(rffi.CArray(VALUE), SHIM_DEPTH * (MAX_ARGC + 1),
                           flavor='raw', immortal=True, zero=True)


class _Nesting(object):
    def __init__(self):
        self.status = 0
        self.argv = 0


_nesting = _Nesting()


def _enter_status():
    """The status cell for one shim call; past SHIM_DEPTH it falls back to a fresh raw cell rather than reusing a slot."""
    d = _nesting.status
    _nesting.status = d + 1
    if d >= SHIM_DEPTH:
        p = lltype.malloc(INTP.TO, 1, flavor='raw')
    else:
        p = rffi.ptradd(_status_pool, d)
    p[0] = rffi.cast(rffi.INT, 0)
    return p


def _leave_status(p):
    d = _nesting.status - 1
    _nesting.status = d
    failed = rffi.cast(lltype.Signed, p[0]) != 0
    if d >= SHIM_DEPTH:
        lltype.free(p, flavor='raw')
    return failed


def _enter_argv(n):
    """An argument buffer for one shim call; the shim copies it to the machine stack before anything can allocate, so this one need not be scanned."""
    assert n <= MAX_ARGC
    d = _nesting.argv
    _nesting.argv = d + 1
    if d >= SHIM_DEPTH:
        return lltype.malloc(rffi.CArray(VALUE), n + 1, flavor='raw')
    return rffi.ptradd(_argv_pool, d * (MAX_ARGC + 1))


def _leave_argv(p):
    d = _nesting.argv - 1
    _nesting.argv = d
    if d >= SHIM_DEPTH:
        lltype.free(p, flavor='raw')


class RubyError(Exception):
    # A call RPyYARV could not make; one that raised becomes a RubyException.
    def __init__(self, mid):
        self.mid = mid


def _failed(name):
    v = rffi.cast(lltype.Signed, rb_take_errinfo())
    raise RubyException(v, name)


def _failed_mid(mid):
    """As _failed, but off the send path, where resolving the name costs a dict lookup on every call that does not raise."""
    _failed(symbols.name_of(mid))


def call0(recv, mid):
    with lltype.scoped_alloc(INTP.TO, 1) as state:
        state[0] = rffi.cast(rffi.INT, 0)
        with rffi.scoped_str2charp(mid) as c_mid:
            v = rb_call0(_v(recv), c_mid, state)
        if rffi.cast(lltype.Signed, state[0]) != 0:
            raise RubyError(mid)
        return rffi.cast(lltype.Signed, v)


def inspect(v):
    p = rb_inspect_cstr(_v(v))
    if not p:
        return '<inspect failed>'
    return rffi.charp2str(p)


def is_array(v):
    return rffi.cast(lltype.Signed, rb_is_array(_v(v))) != 0


def is_symbol(v):
    return rffi.cast(lltype.Signed, rb_is_symbol(_v(v))) != 0


def is_fixnum(v):
    return rffi.cast(lltype.Signed, rb_is_fixnum(_v(v))) != 0


def is_string(v):
    return rffi.cast(lltype.Signed, rb_is_string(_v(v))) != 0


def is_hash(v):
    return rffi.cast(lltype.Signed, rb_is_hash(_v(v))) != 0


def is_nil(v):
    return rffi.cast(lltype.Signed, rb_is_nil(_v(v))) != 0


def is_true(v):
    return rffi.cast(lltype.Signed, rb_is_true(_v(v))) != 0


def is_false(v):
    return rffi.cast(lltype.Signed, rb_is_false(_v(v))) != 0


def num2long(v):
    return rffi.cast(lltype.Signed, rb_num2long(_v(v)))


def ary_len(v):
    return rffi.cast(lltype.Signed, rb_ary_len(_v(v)))


def ary_entry(v, i):
    return rffi.cast(lltype.Signed,
                     rb_ary_entry(_v(v), rffi.cast(rffi.LONG, i)))


def ary_subseq(v, beg, length):
    return rffi.cast(lltype.Signed,
                     rb_ary_subseq(_v(v), rffi.cast(rffi.LONG, beg),
                                   rffi.cast(rffi.LONG, length)))


def hash_aref(hash_v, key):
    with rffi.scoped_str2charp(key) as c_key:
        return rffi.cast(lltype.Signed, rb_hash_aref(_v(hash_v), c_key))


def str_of(v):
    # Length-based read: rb_string_value_cstr raises on an embedded NUL, and that longjmp would cross the RPython frame unprotected.
    n = rffi.cast(lltype.Signed, rb_str_len(_v(v)))
    if n < 0:
        raise RubyError('to_s')
    return rffi.charpsize2str(rb_str_ptr(_v(v)), n)


def sym_of(v):
    p = rb_sym_cstr(_v(v))
    if not p:
        raise RubyError('id2name')
    return rffi.charp2str(p)


_intern_memo = {}


def intern(name):
    """rb_intern is idempotent per name, so a call site that passes the same string every time (RubyVM, InstructionSequence, ...) pays the FFI crossing once."""
    if name in _intern_memo:
        return _intern_memo[name]
    with rffi.scoped_str2charp(name) as c_name:
        r = rffi.cast(lltype.Signed, rb_intern_(c_name))
    _intern_memo[name] = r
    return r


def sym_new(name):
    with rffi.scoped_str2charp(name) as c_name:
        return rffi.cast(lltype.Signed, rb_sym_new(c_name))


def getspecial(type):
    state = _enter_status()
    v = rb_getspecial(rffi.cast(rffi.INT, type), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('$~')
    return ret


def str_intern(v):
    state = _enter_status()
    out = rb_str_intern(rffi.cast(VALUE, v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, out)
    if failed:
        _failed('intern')
    return ret


def toregexp(opt, parts):
    n = len(parts)
    if n > MAX_ARGC:
        raise RubyError('toregexp')
    buf = _enter_argv(n)
    i = 0
    while i < n:
        buf[i] = rffi.cast(VALUE, parts[i])
        i += 1
    state = _enter_status()
    out = rb_toregexp(rffi.cast(rffi.INT, opt), rffi.cast(rffi.INT, n),
                      buf, state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, out)
    _leave_argv(buf)
    if failed:
        _failed('toregexp')
    return ret


def funcallv(recv, rid, args, mid, public_only=False):
    """public_only picks rb_funcallv_public, which honours visibility."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    if public_only:
        v = rb_funcallv_public_id(
            rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
            rffi.cast(rffi.INT, argc), argv, state)
    else:
        v = rb_funcallv_id(
            rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
            rffi.cast(rffi.INT, argc), argv, state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def funcallv_kw(recv, rid, args, mid, public_only=False):
    """args[-1] must be a Hash; it reaches the callee as keywords."""
    argc = len(args)
    if argc > MAX_ARGC or argc < 1:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_funcallv_kw_id(
        rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
        rffi.cast(rffi.INT, argc), argv,
        rffi.cast(rffi.INT, 1 if public_only else 0), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def ary_new(values):
    n = len(values)
    if n > MAX_ARGC:
        return _ary_new_chunked(values)
    buf = _enter_argv(n)
    i = 0
    while i < n:
        buf[i] = rffi.cast(VALUE, values[i])
        i += 1
    ret = rffi.cast(lltype.Signed, rb_ary_new(rffi.cast(rffi.INT, n), buf))
    _leave_argv(buf)
    return ret


def _ary_new_chunked(values):
    """`ary` stays an RPython local, which the conservative stack scan covers between chunks."""
    n = len(values)
    ary = 0
    state = _enter_status()
    ary = rffi.cast(lltype.Signed,
                    rb_ary_new_capa(rffi.cast(rffi.LONG, n), state))
    failed = _leave_status(state)
    if failed:
        _failed('Array.new')
    at = 0
    while at < n:
        count = n - at
        if count > MAX_ARGC:
            count = MAX_ARGC
        with lltype.scoped_alloc(rffi.CArray(VALUE), count + 1) as buf:
            i = 0
            while i < count:
                buf[i] = rffi.cast(VALUE, values[at + i])
                i += 1
            state = _enter_status()
            rb_ary_cat(rffi.cast(VALUE, ary), rffi.cast(rffi.INT, count),
                       buf, state)
            failed = _leave_status(state)
        if failed:
            _failed('Array#concat')
        at += count
    return ary


def call_with_proc(recv, rid, args, proc, mid, kw=False):
    """A foreign Proc as the block; CRuby runs it itself, so its cref and its own break/return stay CRuby's."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_call_with_proc(_v(recv), _v(rid),
                          rffi.cast(rffi.INT, argc), argv, _v(proc),
                          rffi.cast(rffi.INT, 1 if kw else 0), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def call_with_block(recv, rid, args, handle, mid, kw=False):
    """kw: args[-1] is a Hash the callee should see as keywords."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_call_with_block(_v(recv), _v(rid),
                           rffi.cast(rffi.INT, argc), argv,
                           rffi.cast(rffi.LONG, handle),
                           rffi.cast(rffi.INT, 1 if kw else 0), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def install_block_callback(fn):
    """A plain function, not an llhelper pointer: only then does rffi build the enter-RPython-from-C wrapper."""
    rb_set_block_callback(fn)


def install_trampoline_callback(fn):
    """As install_block_callback: a plain function, so rffi builds the enter-RPython-from-C wrapper for it."""
    rb_set_trampoline_callback(fn)


def define_method_entry(klass, rid, private):
    """A CRuby method entry over the generic trampoline."""
    state = _enter_status()
    rb_define_method_id(_v(klass), _v(rid),
                        rffi.cast(rffi.INT, 1 if private else 0), state)
    failed = _leave_status(state)
    if failed:
        _failed('define_method')


def as_signed(v):
    return rffi.cast(lltype.Signed, v)


def as_int(v):
    """An rffi.INT the shim passed; too small for RPython arithmetic until it is widened."""
    return rffi.cast(lltype.Signed, v)


def store_int(p, n):
    p[0] = rffi.cast(rffi.INT, n)


def store_value(p, v):
    p[0] = rffi.cast(VALUE, v)


def read_values(argv, argc):
    """The yielded values out of the shim's machine-stack buffer."""
    n = rffi.cast(lltype.Signed, argc)
    out = [0] * n
    i = 0
    while i < n:
        out[i] = rffi.cast(lltype.Signed, argv[i])
        i += 1
    return out


def read_value_at(argv, i):
    """One argv slot, for a caller that writes each straight into a Frame's locals instead of collecting a list first."""
    return rffi.cast(lltype.Signed, argv[i])


def as_value(n):
    return rffi.cast(VALUE, n)


def ary_resurrect(ary):
    state = _enter_status()
    v = rb_ary_resurrect(_v(ary), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array#dup')
    return ret


def ary_store(ary, idx, val):
    state = _enter_status()
    rb_ary_store_(_v(ary), rffi.cast(rffi.LONG, idx), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('Array#[]=')


def ary_store_fresh(ary, idx, val):
    """No status cell: the shim call cannot raise, so there is nothing to report."""
    rb_ary_store_fresh(_v(ary), rffi.cast(rffi.LONG, idx), _v(val))


def ary_new_capa_fast(capa):
    return rffi.cast(lltype.Signed, rb_ary_new_capa_fast(rffi.cast(rffi.LONG, capa)))


def ary_new_filled_fast(n, val):
    return rffi.cast(lltype.Signed,
                     rb_ary_new_filled_fast(rffi.cast(rffi.LONG, n), _v(val)))


def ary_new_capa(capa):
    state = _enter_status()
    v = rb_ary_new_capa(rffi.cast(rffi.LONG, capa), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array.new')
    return ret


def ary_new_filled(n, val):
    state = _enter_status()
    v = rb_ary_new_filled(rffi.cast(rffi.LONG, n), _v(val), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Array.new')
    return ret


def range_new(low, high, excl):
    state = _enter_status()
    v = rb_range_new_(_v(low), _v(high), rffi.cast(rffi.INT, excl), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Range.new')
    return ret


def gvar_get(name):
    state = _enter_status()
    with rffi.scoped_str2charp(name) as c_name:
        v = rb_gvar_get_(c_name, state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed(name)
    return ret


def gvar_set(name, val):
    state = _enter_status()
    with rffi.scoped_str2charp(name) as c_name:
        rb_gvar_set_(c_name, _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed(name)


def str_concat(parts):
    n = len(parts)
    if n > MAX_ARGC:
        raise RubyError('String#concat')
    with lltype.scoped_alloc(rffi.CArray(VALUE), n + 1) as buf:
        i = 0
        while i < n:
            buf[i] = rffi.cast(VALUE, parts[i])
            i += 1
        return rffi.cast(lltype.Signed,
                         rb_str_concat(rffi.cast(rffi.INT, n), buf))


def top_self():
    return rffi.cast(lltype.Signed, rb_top_self())


def int2inum(n):
    return rffi.cast(lltype.Signed, rb_int2inum(rffi.cast(rffi.LONG, n)))


def float_new(d):
    return rffi.cast(lltype.Signed, rb_float_new(rffi.cast(rffi.DOUBLE, d)))


def str_new(s):
    # Length-carrying, so a literal holding NUL bytes survives the round trip.
    with rffi.scoped_str2charp(s) as c_s:
        return rffi.cast(lltype.Signed, rb_str_new(c_s, len(s)))


def special_consts():
    """(Qfalse, Qnil, Qtrue, FIXNUM_FLAG) as this libruby defines them."""
    with lltype.scoped_alloc(rffi.CArray(VALUE), 4) as out:
        rb_special_consts(rffi.ptradd(out, 0), rffi.ptradd(out, 1),
                          rffi.ptradd(out, 2), rffi.ptradd(out, 3))
        return (rffi.cast(lltype.Signed, out[0]),
                rffi.cast(lltype.Signed, out[1]),
                rffi.cast(lltype.Signed, out[2]),
                rffi.cast(lltype.Signed, out[3]))


def core_classes():
    with lltype.scoped_alloc(rffi.CArray(VALUE), NCLASS) as out:
        rb_core_classes(out)
        result = [0] * NCLASS
        i = 0
        while i < NCLASS:
            result[i] = rffi.cast(lltype.Signed, out[i])
            i += 1
        return result


def obj_written(a, b):
    return rb_obj_written(_v(a), _v(b))


def wb_direct():
    return rffi.cast(lltype.Signed, rb_wb_direct()) != 0


RANGE_BEG = 0
RANGE_END = 1
RANGE_EXCL = 2


def range_part(v, which):
    """One Range field, or Qundef when v is not a direct Range."""
    return rffi.cast(lltype.Signed,
                     rb_range_part(_v(v), rffi.cast(rffi.INT, which)))


def struct_member_index(klass, rid):
    return rffi.cast(lltype.Signed,
                     rb_struct_member_index(_v(klass), _v(rid)))


def struct_get(obj, index):
    return rffi.cast(lltype.Signed,
                     rb_struct_get(_v(obj), rffi.cast(rffi.INT, index)))


def struct_set(obj, index, v):
    rb_struct_set(_v(obj), rffi.cast(rffi.INT, index), _v(v))


def class_ivar_get(obj, rid):
    return rffi.cast(lltype.Signed, rb_class_ivar_get(_v(obj), _v(rid)))


def ivar_defined(obj, rid):
    return rffi.cast(lltype.Signed, rb_ivar_defined(_v(obj), _v(rid))) != 0


def const_defined(klass, rid, inherit):
    return rffi.cast(lltype.Signed,
                     rb_const_defined(_v(klass), _v(rid), inherit)) != 0


def method_defined(obj, rid, include_private):
    return rffi.cast(lltype.Signed,
                     rb_method_defined(_v(obj), _v(rid), include_private)) != 0


def str_getbyte(string, index):
    return rffi.cast(lltype.Signed, rb_str_getbyte(_v(string), _v(index)))


def call_super(klass, owner, recv, rid, args, mid, kw=False, proc=0):
    """The method after owner's along klass's chain, called on recv; where `super` lands when CRuby owns it."""
    argc = len(args)
    if argc > MAX_ARGC:
        raise RubyError(symbols.name_of(mid))
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_call_super(rffi.cast(VALUE, klass), rffi.cast(VALUE, owner),
                      rffi.cast(VALUE, recv), rffi.cast(VALUE, rid),
                      rffi.cast(rffi.INT, argc), argv,
                      rffi.cast(rffi.INT, 1 if kw else 0),
                      rffi.cast(VALUE, proc), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed_mid(mid)
    return ret


def str_append(string, other):
    """String#<< of one String onto another, or Qundef when only rb_str_concat can do it."""
    return rffi.cast(lltype.Signed, rb_str_append(_v(string), _v(other)))


def str_setbyte(string, index, v):
    return rffi.cast(lltype.Signed,
                     rb_str_setbyte(_v(string), _v(index), _v(v)))


def method_owner(klass, rid):
    """The module klass resolves rid through, or Qnil when it has none."""
    return rffi.cast(lltype.Signed, rb_method_owner(_v(klass), _v(rid)))


def cvar_get(klass, rid):
    state = _enter_status()
    v = rb_cvar_get(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('class variable')
    return ret


def cvar_set(klass, rid, val):
    state = _enter_status()
    rb_cvar_set(_v(klass), _v(rid), _v(val), state)
    if _leave_status(state):
        _failed('class variable')


def cvar_defined(klass, rid):
    return rffi.cast(lltype.Signed,
                     rb_cvar_defined(_v(klass), _v(rid))) != 0


def is_singleton_class(klass):
    return rffi.cast(lltype.Signed, rb_is_singleton_class(_v(klass))) != 0


def dir_of(path):
    """dirname(realpath(path)), what __dir__ answers for a file; Qundef when it has no realpath."""
    return rffi.cast(lltype.Signed, rb_dir_of(_v(path)))


def current_receiver():
    """The self of the frame running now."""
    return rffi.cast(lltype.Signed, rb_current_receiver())


def sym_name(sym):
    """The frozen String Symbol#name returns, or Qundef for a dynamic symbol."""
    return rffi.cast(lltype.Signed, rb_sym_name(_v(sym)))


def class_le(klass, target):
    """Module#<=: 1 below or equal, 0 not, -1 when target is not a Module."""
    return rffi.cast(lltype.Signed, rb_class_le(_v(klass), _v(target)))


def responds(klass, sym):
    """Whether every instance of klass responds to sym: 1 yes, 0 no, -1 unanswerable per class."""
    return rffi.cast(lltype.Signed, rb_responds(_v(klass), _v(sym)))


def ary_to_ary(obj):
    """rb_ary_to_ary: to_ary when the object has one, otherwise a one-element Array."""
    state = _enter_status()
    v = rb_ary_to_ary(_v(obj), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('to_ary')
    return ret


def super_owner(klass, owner, rid):
    """The module `super` from owner's copy of rid reaches next, or Qnil when there is none."""
    return rffi.cast(lltype.Signed,
                     rb_super_owner(_v(klass), _v(owner), _v(rid)))


def define_class(cbase, rid, super_v):
    state = _enter_status()
    v = rb_define_class_(_v(cbase), _v(rid), _v(super_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Class.new')
    return ret


def define_module(cbase, rid):
    state = _enter_status()
    v = rb_define_module_(_v(cbase), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Module.new')
    return ret


def class_superclass(klass):
    state = _enter_status()
    v = rb_class_superclass(_v(klass), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        rb_take_errinfo()
        return 0
    return ret


def singleton_class(obj):
    state = _enter_status()
    v = rb_singleton_class(_v(obj), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('singleton_class')
    return ret


def obj_alloc_fast(klass):
    return rffi.cast(lltype.Signed, rb_obj_alloc_fast(_v(klass)))


def alloc_default(klass):
    """The unprotected Class#allocate: Qundef whenever the shim is not sure the allocation cannot raise."""
    return rffi.cast(lltype.Signed, rb_alloc_default(_v(klass)))


def obj_alloc(klass):
    state = _enter_status()
    v = rb_obj_alloc(_v(klass), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('allocate')
    return ret


def const_get(klass, rid):
    state = _enter_status()
    v = rb_const_get_(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('const_get')
    return ret


def const_at(klass, rid):
    state = _enter_status()
    v = rb_const_at_(_v(klass), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('const_at')
    return ret


def const_set(klass, rid, val):
    state = _enter_status()
    rb_const_set_(_v(klass), _v(rid), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('const_set')


def ivar_get(obj, rid):
    state = _enter_status()
    v = rb_ivar_get_(_v(obj), _v(rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('instance_variable_get')
    return ret


def ivar_set(obj, rid, val):
    state = _enter_status()
    rb_ivar_set_(_v(obj), _v(rid), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('instance_variable_set')


LAYOUT_N = 14


def object_layout():
    out = [0] * LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, LAYOUT_N) as buf:
        rb_object_layout(buf)
        for i in range(LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


FLOAT_LAYOUT_N = 3


def float_layout():
    out = [0] * FLOAT_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, FLOAT_LAYOUT_N) as buf:
        rb_float_layout(buf)
        for i in range(FLOAT_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


ARRAY_LAYOUT_N = 10


def array_layout():
    out = [0] * ARRAY_LAYOUT_N
    with lltype.scoped_alloc(INTP.TO, ARRAY_LAYOUT_N) as buf:
        rb_array_layout(buf)
        for i in range(ARRAY_LAYOUT_N):
            out[i] = rffi.cast(lltype.Signed, buf[i])
    return out


def str_eq(a, b):
    return rffi.cast(lltype.Signed, rb_str_eq(_v(a), _v(b)))


def shape_iv_index(shape_id, rid):
    """The field slot holding rid in shape_id: >= 0 found, -1 provably absent, -2 fast path unusable."""
    with lltype.scoped_alloc(INTP.TO, 1) as idx:
        idx[0] = rffi.cast(rffi.INT, -1)
        found = rffi.cast(lltype.Signed,
                          rb_shape_iv_index(rffi.cast(rffi.UINT, shape_id),
                                            _v(rid), idx))
        slot = rffi.cast(lltype.Signed, idx[0])
    if found == 1:
        return slot
    if found == 0:
        return -1
    return -2


def shape_add_ivar_slot(before, after, rid):
    """The slot a raw store may put rid in when it moves an object from before to after, or -1 when only rb_ivar_set may."""
    with lltype.scoped_alloc(INTP.TO, 1) as idx:
        idx[0] = rffi.cast(rffi.INT, -1)
        ok = rffi.cast(lltype.Signed,
                       rb_shape_add_ivar_fits(rffi.cast(rffi.UINT, before),
                                              rffi.cast(rffi.UINT, after),
                                              _v(rid), idx))
        slot = rffi.cast(lltype.Signed, idx[0])
    if ok == 1:
        return slot
    return -1


def proc_new(handle):
    """A Proc whose call re-enters RPyYARV through the block callback."""
    state = _enter_status()
    v = rb_proc_new(rffi.cast(rffi.LONG, handle), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Proc.new')
    return ret


def pop_dead_handle():
    return rffi.cast(lltype.Signed, rb_pop_dead_handle())


def is_proc(v):
    return rffi.cast(lltype.Signed, rb_is_proc(_v(v))) != 0


def is_class(v):
    return rffi.cast(lltype.Signed, rb_is_class(_v(v))) != 0


def obj_is_kind_of(obj, klass):
    state = _enter_status()
    r = rffi.cast(lltype.Signed, rb_obj_is_kind_of(_v(obj), _v(klass),
                                                   state))
    failed = _leave_status(state)
    if failed:
        _failed('kind_of?')
    return r != 0


def swap_errinfo(v):
    return rffi.cast(lltype.Signed, rb_swap_errinfo(_v(v)))


def cleanup_with_error(v):
    return rffi.cast(lltype.Signed, rb_cleanup_with_error(_v(v)))


def hash_new(capa):
    state = _enter_status()
    v = rb_hash_new_capa(rffi.cast(rffi.LONG, capa), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash.new')
    return ret


def hash_aset(hash_v, key, val):
    state = _enter_status()
    rb_hash_aset_(_v(hash_v), _v(key), _v(val), state)
    failed = _leave_status(state)
    if failed:
        _failed('Hash#[]=')


def hash_resurrect(hash_v):
    state = _enter_status()
    v = rb_hash_resurrect(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#dup')
    return ret


def hash_size(hash_v):
    return rffi.cast(lltype.Signed, rb_hash_size(_v(hash_v)))


def hash_lookup(hash_v, key):
    """Qundef when the key is absent."""
    state = _enter_status()
    v = rb_hash_lookup(_v(hash_v), _v(key), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#[]')
    return ret


def hash_aref_value(hash_v, key):
    """Hash#[] whole, defaults included; the VALUE-keyed one, unlike hash_aref's C-string key."""
    state = _enter_status()
    v = rb_hash_aref_full(_v(hash_v), _v(key), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#[]')
    return ret


def hash_lookup_fast(hash_v, key):
    """Unprotected Hash lookup for a key that cannot call Ruby; Q_UNDEF on miss."""
    return rffi.cast(lltype.Signed, rb_hash_lookup_fast(_v(hash_v), _v(key)))


def hash_aset_fast(hash_v, key, val):
    """Unprotected Hash store; only for an unfrozen plain Hash and a key that cannot call Ruby."""
    rb_hash_aset_fast(_v(hash_v), _v(key), _v(val))


def hash_pairs(hash_v):
    """[k0, v0, k1, v1, ...] of a Hash in entry order, one C call."""
    state = _enter_status()
    v = rb_hash_pairs(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#each')
    return ret


def alias_variable(sym1, sym2):
    """`alias $new $old`, as vm.c's core#set_variable_alias does it."""
    state = _enter_status()
    rb_alias_variable(_v(sym1), _v(sym2), state)
    failed = _leave_status(state)
    if failed:
        _failed('alias')


def set_include(set_v, elt):
    """Qundef for anything but a direct core Set."""
    state = _enter_status()
    v = rb_set_include(_v(set_v), _v(elt), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Set#include?')
    return ret


def str_push(string, other):
    """Qundef unless both are Strings."""
    state = _enter_status()
    v = rb_str_push(_v(string), _v(other), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('String#<<')
    return ret


def str_start_with(string, prefix):
    return rffi.cast(lltype.Signed, rb_str_start_with(_v(string), _v(prefix)))


def int_to_s(v):
    return rffi.cast(lltype.Signed, rb_int_to_s_fast(_v(v)))


def str_gsub2(recv, pat, rep, rid, mid):
    """String#gsub / #gsub! of a Regexp|String pattern and a backref-free String replacement."""
    state = _enter_status()
    v = rb_str_gsub2(_v(recv), _v(pat), _v(rep), rffi.cast(VALUE, rid), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed_mid(mid)
    return ret


def str_eq_tilde(a, b):
    """=~ between a String and a Regexp in either order: Qundef for the wrong types, a raise inside the match comes back out."""
    state = _enter_status()
    v = rb_str_eq_tilde(_v(a), _v(b), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('=~')
    return ret


def reg_eqq(re, s):
    state = _enter_status()
    v = rb_reg_eqq_fast(_v(re), _v(s), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('===')
    return ret


def last_match0():
    return rffi.cast(lltype.Signed, rb_last_match0())


def last_match1(n):
    return rffi.cast(lltype.Signed, rb_last_match1(_v(n)))


def str_match(s, re):
    state = _enter_status()
    v = rb_str_match_fast(_v(s), _v(re), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('match')
    return ret


def str_casecmp(a, b):
    return rffi.cast(lltype.Signed, rb_str_casecmp_fast(_v(a), _v(b)))


def str_cmp(a, b):
    return rffi.cast(lltype.Signed, rb_str_cmp_fast(_v(a), _v(b)))


def str_downcase(s):
    return rffi.cast(lltype.Signed, rb_str_downcase_fast(_v(s)))


def str_downcase_bang(s):
    return rffi.cast(lltype.Signed, rb_str_downcase_bang(_v(s)))


def str_upcase(s):
    return rffi.cast(lltype.Signed, rb_str_upcase_fast(_v(s)))


def str_upcase_bang(s):
    return rffi.cast(lltype.Signed, rb_str_upcase_bang(_v(s)))


def sym_to_s(v):
    return rffi.cast(lltype.Signed, rb_sym_to_s_fast(_v(v)))


def str_dup(v):
    return rffi.cast(lltype.Signed, rb_str_dup_fast(_v(v)))


def str_length(v):
    return rffi.cast(lltype.Signed, rb_str_length_fast(_v(v)))


def str_tr1(s, frm, to):
    return rffi.cast(lltype.Signed, rb_str_tr1(_v(s), _v(frm), _v(to)))


def str_index_of(s, needle):
    return rffi.cast(lltype.Signed, rb_str_index_of(_v(s), _v(needle)))


def str_match_p(s, re):
    """Qundef for the wrong types; a raise inside the search comes back out."""
    state = _enter_status()
    v = rb_str_match_p(_v(s), _v(re), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('match?')
    return ret


def str_match_p_fast(s, re):
    """The unprotected match?: Qundef whenever the shim is not sure the search cannot raise, same as a type mismatch."""
    return rffi.cast(lltype.Signed, rb_str_match_p_fast(_v(s), _v(re)))


def str_format(fmt, args):
    """Kernel#format / Kernel#sprintf; the caller keeps len(args) within MAX_ARGC, as every other variable-argc boot call here does."""
    argc = len(args)
    argv = _enter_argv(argc)
    i = 0
    while i < argc:
        argv[i] = rffi.cast(VALUE, args[i])
        i += 1
    state = _enter_status()
    v = rb_sprintf_(rffi.cast(rffi.INT, argc), argv, _v(fmt), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    _leave_argv(argv)
    if failed:
        _failed('format')
    return ret


def cgi_escape_html(s):
    return rffi.cast(lltype.Signed, rb_cgi_escape_html(_v(s)))


def str_empty_p(v):
    return rffi.cast(lltype.Signed, rb_str_empty_p(_v(v)))


def hash_empty_p(v):
    return rffi.cast(lltype.Signed, rb_hash_empty_p(_v(v)))


def str_uminus(v):
    return rffi.cast(lltype.Signed, rb_str_uminus(_v(v)))


def ary_pop(v):
    return rffi.cast(lltype.Signed, rb_ary_pop_fast(_v(v)))


def ary_push1(v, elt):
    return rffi.cast(lltype.Signed, rb_ary_push1(_v(v), _v(elt)))


def ary_shift(v):
    return rffi.cast(lltype.Signed, rb_ary_shift_fast(_v(v)))


def ary_unshift1(v, elt):
    return rffi.cast(lltype.Signed, rb_ary_unshift1(_v(v), _v(elt)))


def ary_hash_freeze(v):
    return rffi.cast(lltype.Signed, rb_ary_hash_freeze(_v(v)))


def hash_keys_fast(hash_v):
    """[k0, k1, ...] of a Hash in entry order, one C call; distinct from rubycall.hash_keys, which serves the keyword-splat error path."""
    state = _enter_status()
    v = rb_hash_keys_fast(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#keys')
    return ret


def ary_flatten_bang1(v):
    return rffi.cast(lltype.Signed, rb_ary_flatten_bang1(_v(v)))


def ss_pos(v):
    return rffi.cast(lltype.Signed, rb_ss_pos(_v(v)))


def ss_set_pos(v, pos):
    return rffi.cast(lltype.Signed, rb_ss_set_pos(_v(v), _v(pos)))


def ss_eos_p(v):
    return rffi.cast(lltype.Signed, rb_ss_eos_p(_v(v)))


def ss_matched_size(v):
    return rffi.cast(lltype.Signed, rb_ss_matched_size(_v(v)))


def ss_skip(v, re):
    """Qundef for the wrong types; a raise inside the match comes back out."""
    state = _enter_status()
    r = rb_ss_skip(_v(v), _v(re), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, r)
    if failed:
        _failed('skip')
    return ret


def str_byteslice2(s, beg, length):
    return rffi.cast(lltype.Signed,
                     rb_str_byteslice2(_v(s), _v(beg), _v(length)))


def str_force_encoding_fast(s, enc):
    """The unprotected String#force_encoding: Qundef whenever the shim is not sure the association cannot raise."""
    return rffi.cast(lltype.Signed, rb_str_force_encoding_fast(_v(s), _v(enc)))


def unpack1_double(s, fmt, offset):
    """The unprotected String#unpack1: Qundef unless the format is "E" and the eight bytes are in range."""
    return rffi.cast(lltype.Signed,
                     rb_unpack1_double(_v(s), _v(fmt), _v(offset)))


def str_bytesize(v):
    return rffi.cast(lltype.Signed, rb_str_len(_v(v)))


def str_ascii_only_p(v):
    return rffi.cast(lltype.Signed, rb_str_ascii_only_p(_v(v)))


def pack_double_into(ary, fmt, buf):
    """The unprotected Array#pack: Qundef unless the format is "E" and the one Float goes into a writable buffer."""
    return rffi.cast(lltype.Signed,
                     rb_pack_double_into(_v(ary), _v(fmt), _v(buf)))


def hash_delete(hash_v, key):
    state = _enter_status()
    rb_hash_delete(_v(hash_v), _v(key), state)
    failed = _leave_status(state)
    if failed:
        _failed('Hash#delete')


def hash_keys(hash_v):
    state = _enter_status()
    v = rb_hash_keys(_v(hash_v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('Hash#keys')
    return ret


def to_hash_type(v):
    state = _enter_status()
    r = rb_to_hash_type(_v(v), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, r)
    if failed:
        _failed('Hash()')
    return ret


def splat_array(ary, flag):
    state = _enter_status()
    v = rb_splat_array(_v(ary), rffi.cast(rffi.INT, flag), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('to_a')
    return ret


def concat_array(ary1, ary2, to):
    state = _enter_status()
    v = rb_concat_array(_v(ary1), _v(ary2), rffi.cast(rffi.INT, 1 if to else 0),
                        state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('to_a')
    return ret


def vm_core():
    return rffi.cast(lltype.Signed, rb_vm_core())


def keyword_error(kind, keys):
    """The ArgumentError VALUE for 'missing' or 'unknown' keywords; keys is an Array of Symbols."""
    state = _enter_status()
    with rffi.scoped_str2charp(kind) as c_kind:
        v = rb_keyword_error(c_kind, _v(keys), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('ArgumentError')
    return ret


def arity_error(given, min_argc, max_argc):
    """The ArgumentError VALUE; -1 for max_argc means unlimited."""
    state = _enter_status()
    v = rb_arity_error(rffi.cast(rffi.INT, given),
                       rffi.cast(rffi.INT, min_argc),
                       rffi.cast(rffi.INT, max_argc), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('ArgumentError')
    return ret


def local_jump_error(mesg, val, reason):
    """The LocalJumpError VALUE; reason is a ruby_tag_type."""
    state = _enter_status()
    with rffi.scoped_str2charp(mesg) as c_mesg:
        v = rb_local_jump_error(c_mesg, _v(val),
                                rffi.cast(rffi.INT, reason), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('LocalJumpError')
    return ret


def set_block_unwind():
    """Tell the shim the block it is running left early; see boot_shim.h."""
    rb_set_block_unwind()




def bop_mask():
    """(pair count, one bit per redefined pair) as the shim orders them; the count is separate so the mask may use every bit."""
    with lltype.scoped_alloc(INTP.TO, 1) as count:
        count[0] = rffi.cast(rffi.INT, 0)
        v = rffi.cast(lltype.Signed, rb_bop_mask(count))
        return rffi.cast(lltype.Signed, count[0]), v


def require_resolve(fname):
    """(REQ_*, expanded path VALUE); the path is 0 unless the answer is REQ_RB."""
    path = 0
    kind = REQ_FOREIGN
    with lltype.scoped_alloc(rffi.CArray(VALUE), 1) as out:
        out[0] = rffi.cast(VALUE, 0)
        with lltype.scoped_alloc(INTP.TO, 1) as state:
            state[0] = rffi.cast(rffi.INT, 0)
            kind = rffi.cast(lltype.Signed,
                             rb_require_resolve(_v(fname), out, state))
        path = rffi.cast(lltype.Signed, out[0])
    if kind != REQ_RB:
        return kind, 0
    return kind, path


def provide(path):
    state = _enter_status()
    rb_provide_(_v(path), state)
    failed = _leave_status(state)
    if failed:
        _failed('$LOADED_FEATURES')


def absolute_path(fname, base):
    state = _enter_status()
    v = rb_absolute_path(_v(fname), _v(base), state)
    failed = _leave_status(state)
    ret = rffi.cast(lltype.Signed, v)
    if failed:
        _failed('File.absolute_path')
    return ret


def gc_register(v):
    rb_gc_register(_v(v))


def gc_mark_value(v):
    rb_gc_mark_value(rffi.cast(VALUE, v))


def gc_mark_maybe(w):
    """A machine word that may or may not be a VALUE; rb_gc_mark_maybe checks."""
    rb_gc_mark_maybe(rffi.cast(VALUE, w))


def gc_start():
    rb_gc_start()


def set_mark_hook(fn):
    rb_gc_set_mark_hook(fn)


def set_handle_mark(fn):
    """As install_block_callback: a plain function, so rffi builds the enter-RPython-from-C wrapper for it."""
    rb_set_handle_mark(fn)


def fiber_killed_value():
    return rffi.cast(lltype.Signed, rb_fiber_killed_value())


def rethrow_if_fiber_kill(v):
    """Returns for anything but Fiber#kill, which resumes its fatal unwind here rather than crossing back into CRuby as a raise."""
    rb_rethrow_if_fiber_kill(_v(v))


def set_fiber_hooks(park, unpark, born, died, base_slot, top_slot):
    """As install_block_callback: plain functions, so rffi builds the enter-RPython-from-C wrappers."""
    rb_set_fiber_hooks(park, unpark, born, died, base_slot, top_slot)


def set_const_hook(fn):
    """As install_block_callback: a plain function, so rffi builds the enter-RPython-from-C wrapper for it."""
    rb_set_const_hook(fn)


def set_method_hook(fn):
    rb_set_method_hook(fn)


class _Node(object):
    # The compiled main script, kept so run_node() can hand it back to CRuby.
    def __init__(self):
        self.ptr = lltype.nullptr(VOIDP.TO)


node = _Node()


def _uninstalled_dirs():
    """CRuby derives its load path from the executable, and that is not $BUILD/ruby: the uninstalled build's lib/ and extensions, the same set ruby-runner.c puts in RUBYLIB."""
    build = os.environ.get('RPYYARV_BUILD')
    if build is None or build == '':
        return []
    cut = build.rfind('/')
    if cut <= 0:
        return []
    ext = build + '/.ext'
    # rbconfig.rb is generated into the build root, not into .ext/common.
    return [build[:cut] + '/lib', ext + '/common', build, ext + '/' + _ARCH]


def _boot_argv(argv):
    """-I, not a setenv of RUBYLIB: allocating before ruby_init moves the heap enough to swing AWFY towers by 38%, and CRuby reads the two the same way."""
    args = [argv[0]]
    if os.environ.get('RPYYARV_GEMS') != '1':
        args.append('--disable-gems')
    for d in _uninstalled_dirs():
        args.append('-I' + d)
    return args + argv[1:]


def boot(argv):
    """Return (iseqw, status). iseqw is 0 when there is no ISeq to run."""
    argv = _boot_argv(argv)
    # Never freed: ruby_sysinit keeps this pointer in origarg (ruby.c) for the process lifetime.
    c_argv = rffi.liststr2charpp(argv)
    with lltype.scoped_alloc(INTP.TO, 1) as status:
        status[0] = rffi.cast(rffi.INT, 0)
        n = rb_boot(rffi.cast(rffi.INT, len(argv)), c_argv, status)
        if not n:
            return 0, rffi.cast(lltype.Signed, status[0])
        node.ptr = n
        return rffi.cast(lltype.Signed, rb_iseqw_new(n)), 0


def run_node():
    """Runs the script and cleans up; the answer is the process exit status."""
    return rffi.cast(lltype.Signed, rb_run_node(node.ptr))


def cleanup(status):
    return rffi.cast(lltype.Signed, rb_cleanup(rffi.cast(rffi.INT, status)))
