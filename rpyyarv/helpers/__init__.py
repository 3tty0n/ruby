"""opt_* fast paths: no rb_* call, else Q_UNDEF (vm_insnhelper.c:6880)."""
from __future__ import absolute_import

from rpyyarv.helpers.core import *
from rpyyarv.helpers.string import *
from rpyyarv.helpers.numeric import *
from rpyyarv.helpers.symbol import *
from rpyyarv.helpers.array import *
from rpyyarv.helpers.hash import *
from rpyyarv.helpers.regexp import *
from rpyyarv.helpers.object import *

from rpyyarv.helpers.core import (
    _ARY_MID, _Bops, _FLT_AS_INT, _FLT_MID, _INT_MID, _Modules, _SYM_MID,
    _ary_op, _core_op, _cruby_owns, _dbl, _fix2, _flt2, _flt_op, _flt_owns,
    _from_dbl, _from_int, _int_op, _int_owns, _mixable, _owned_by_core,
    _str_eq_op, _sym_op)
from rpyyarv.helpers.string import _str_eq
from rpyyarv.helpers.array import _ary_eq_false
from rpyyarv.helpers.hash import _hash_key_cannot_reenter
from rpyyarv.helpers.symbol import _sym_eq
from rpyyarv.helpers.numeric import _both_positive, _fdiv
from rpyyarv.helpers.object import _real_class_of
