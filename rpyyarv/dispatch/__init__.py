"""Lookup is elidable in (klass, mid, version), so a send folds to one guard."""
from __future__ import absolute_import

from rpyyarv.dispatch.core import *
from rpyyarv.dispatch.trampoline import *
from rpyyarv.dispatch.classes import *
from rpyyarv.dispatch.consts import *
from rpyyarv.dispatch.caches import *
from rpyyarv.dispatch.layout import *

# "from X import *" skips underscore-prefixed names; the flat module used
# to expose these too, so pull every one of them into the facade by name.
from rpyyarv.dispatch.core import (_table_for, _walk, _module_lookup,
    _lookup, _own_lookup, _lookup_core, _is_known_class, _is_known_module)
from rpyyarv.dispatch.trampoline import (_Trampoline, _install_trampoline,
    _record_ancestry, _TC_SIZE, _TC_MASK, _tc_rids, _tc_klasses, _tc_mids,
    _tc_entries, _bmethod_idents)
from rpyyarv.dispatch.classes import _reopened
from rpyyarv.dispatch.consts import (_Consts, _const_cached,
    _const_at_cached, _const_at_fill, _const_fill,
    _const_from_cached, _const_from_fill)
from rpyyarv.dispatch.caches import (_Owners, _owner_of, _fill_owner,
    _responds, _fill_responds, _SymNames, _sym_name, _fill_sym_name,
    _kind_of, _fill_kind_of, _StructSlots, _struct_index, _fill_struct_index,
    _super_owner, _fill_super_owner, _Slots,
    _StructArity, _struct_arity, _fill_struct_arity)
from rpyyarv.dispatch.layout import (_data_fields, _class_fields,
    _ivar_get_slow, _Barrier, _Trans, _iv_transition, _ivar_add_slow,
    _ivar_set_slow)
