"""Primitive/builtin fast paths invoke falls through to."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import debug
from rpyyarv import gcroots
from rpyyarv import helpers
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.iseq import W_CallInfo
from rpyyarv.rlib import dont_look_inside, unroll_safe

from rpyyarv.interp.consts_ids import ENC_FIND

# Above this, back to CRuby: the loop is traced, not a jitdriver.
ARY_NEW_BLOCK_MAX = 64


# rb_ary_resize nil-fills; past this the second pass costs more.
ARY_NEW_FILL_MAX = 128


@dont_look_inside
def _array_new(size, fill, argc):
    """rb_ary_s_new for a direct Array (array.c:1071); Qundef otherwise."""
    # Out of line: inlining these grew cd's and havlak's traces ~5%.
    if argc > 2:
        return value.Q_UNDEF
    if argc == 0:
        return rubycall.ary_new_capa(0)
    # FIXNUM_P: to_int, to_ary and Bignum take rb_ary_initialize's slow paths.
    if not value.is_fixnum(size):
        return value.Q_UNDEF
    n = value.fix2int(size)
    if n < 0:
        return value.Q_UNDEF
    if argc == 2 and n > ARY_NEW_FILL_MAX:
        return value.Q_UNDEF
    return rubycall.ary_new_filled(n, fill)


@unroll_safe
def _array_new_block(frame, recv_at, argc, w_block):
    """Traced through: an enclosing-local read forces caller's virtualizable."""
    # argc 0 and argc 2 are rb_warning cases in rb_ary_initialize.
    if argc != 1:
        return value.Q_UNDEF
    size = frame.stack[recv_at + 1]
    if not value.is_fixnum(size):
        return value.Q_UNDEF
    n = value.fix2int(size)
    if n < 0 or n > ARY_NEW_BLOCK_MAX:
        return value.Q_UNDEF
    ary = rubycall.ary_new_capa(n)
    # Into the receiver's slot: the frame marks it, nothing else holds it.
    frame.stack[recv_at] = ary
    i = 0
    while i < n:
        v = call_block(w_block, [value.int2fix(i)])
        # rb_ary_store, so a block that raises leaves the length CRuby would.
        rubycall.ary_store_fresh(ary, i, v)
        i += 1
    _drop(frame, recv_at)
    return ary


def _array_each_slice(ary, size, w_block):
    """Enumerable#each_slice for a plain Array, no CRuby callback per slice."""
    at = 0
    while at < value.ary_len(ary):
        remaining = value.ary_len(ary) - at
        count = size if size < remaining else remaining
        part = boot.ary_subseq(ary, at, count)
        call_block(w_block, [part])
        at += count
    return ary


P_REQ = symbols.intern('req')
P_OPT = symbols.intern('opt')
P_REST = symbols.intern('rest')
P_KEYREQ = symbols.intern('keyreq')
P_KEY = symbols.intern('key')
P_KEYREST = symbols.intern('keyrest')
P_BLOCK = symbols.intern('block')


def _local_name(w_iseq, slot):
    if slot < 0 or slot >= len(w_iseq.local_names):
        return ''
    return w_iseq.local_names[slot]


def _param(out, kind, name):
    """An anonymous parameter is one element, as rb_iseq_parameters emits."""
    if name == '':
        boot.ary_push1(out, rubycall.ary_new([rubycall.sym_value(kind)]))
    else:
        boot.ary_push1(out, rubycall.ary_new(
            [rubycall.sym_value(kind),
             rubycall.sym_value(symbols.intern(name))]))


def _iseq_parameters(w_iseq, is_proc):
    """rb_iseq_parameters (iseq.c): the ISeq table, not CRuby's cfunc view."""
    lead = P_OPT if is_proc else P_REQ
    out = rubycall.ary_new([])
    gcroots.hold(out)
    try:
        i = 0
        while i < w_iseq.nparams:
            _param(out, lead, _local_name(w_iseq, i))
            i += 1
        n_opt = len(w_iseq.opt_table) - 1 if len(w_iseq.opt_table) > 0 else 0
        i = 0
        while i < n_opt:
            _param(out, P_OPT, _local_name(w_iseq, w_iseq.nparams + i))
            i += 1
        if w_iseq.rest_start >= 0:
            _param(out, P_REST, _local_name(w_iseq, w_iseq.rest_start))
        i = 0
        while i < w_iseq.post_num:
            _param(out, lead, _local_name(w_iseq, w_iseq.post_start + i))
            i += 1
        i = 0
        while i < len(w_iseq.kw_table):
            kind = P_KEYREQ if i < w_iseq.kw_required else P_KEY
            _param(out, kind, symbols.name_of(w_iseq.kw_table[i]))
            i += 1
        if w_iseq.kwrest >= 0:
            _param(out, P_KEYREST, _local_name(w_iseq, w_iseq.kwrest))
        if w_iseq.block_start >= 0:
            _param(out, P_BLOCK, _local_name(w_iseq, w_iseq.block_start))
    finally:
        gcroots.release(out)
    return out


def _integer_step(recv, limit, step, w_block):
    """Integer#step over fixnums; every value stays inside [recv, limit]."""
    i = value.fix2int(recv)
    stop = value.fix2int(limit)
    by = value.fix2int(step)
    if by > 0:
        while i <= stop:
            call_block(w_block, [value.int2fix(i)])
            i += by
    else:
        while i >= stop:
            call_block(w_block, [value.int2fix(i)])
            i += by
    return recv


def _array_each_with_index(ary, w_block):
    """Enumerable#each_with_index for a plain Array, no CRuby per element."""
    i = 0
    # Length re-read each pass: mutation mid-iteration behaves like CRuby.
    while i < value.ary_len(ary):
        call_block(w_block, [value.ary_at(ary, i), value.int2fix(i)])
        i += 1
    return ary


# A deeper chain than this is a runaway; caller only ever reads the top anyway.
MAX_BACKTRACE = 4096


# What InstructionSequence.compile names a fileless source (prelude.rb).
COMPILED_PATH = '<compiled>'


def _running_method(frame):
    """__method__: the innermost method frame's entry; nil at the toplevel."""
    f = frame
    n = 0
    while f is not None and n < MAX_SCOPES:
        entry = f.entry
        if entry is not None:
            return rubycall.sym_value(entry.mid)
        f = f.defining_frame
        n += 1
    return value.Q_NIL


@dont_look_inside
def _backtrace():
    """path, line and label of every live RPyYARV frame, innermost first."""
    ary = rubycall.ary_new([])
    # Held: the strings below allocate, and an RPython list is no GC root.
    gcroots.hold(ary)
    try:
        f = gcroots.state.top
        n = 0
        at = 0
        while f is not None and n < MAX_BACKTRACE:
            n += 1
            w_iseq = f.w_iseq
            path = w_iseq.path
            if path == COMPILED_PATH or path == '':
                f = f.prev_frame
                continue
            rubycall.ary_store(ary, at, boot.str_new(path))
            rubycall.ary_store(ary, at + 1,
                               value.int2fix(w_iseq.line_for(f.pc)))
            rubycall.ary_store(ary, at + 2, boot.str_new(w_iseq.name))
            at += 3
            f = f.prev_frame
    finally:
        gcroots.release(ary)
    return ary


@dont_look_inside
def _dir_of(frame):
    """__dir__ for this frame's ISeq file; Qundef when it has none."""
    path = frame.w_iseq.path
    if path == '' or path.startswith('<'):
        return value.Q_UNDEF
    return boot.dir_of(boot.str_new(path))


class _Proxy(object):
    # Quasi-immutable: the compare folds away; prebuilt, so not plain.
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


class _FiberKill(object):
    """RUBY_FATAL_FIBER_KILLED (internal/thread.h), asked of the shim once."""
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


fiber_kill = _FiberKill()


# rb_block_param_proxy's stand-in (insns.def:144): a Symbol, unmarked.
proxy = _Proxy()


class _Encodings(object):
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


encodings = _Encodings()


class _RegexpClass(object):
    """Regexp itself, cached to tell Regexp.last_match from a method call."""
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


regexp_class = _RegexpClass()


# Encoding.find is pure and Encodings immortal: one call per name.
enc_cache = {}


SPACESHIP_CI = W_CallInfo(helpers.SPACESHIP, 1)


@unroll_safe
def _comparable_op(frame, mid, recv_at):
    """Comparable#< and friends: <=> natively, not out through compar.c."""
    recv = frame.stack[recv_at]
    arg = frame.stack[recv_at + 1]
    cmp = invoke(frame, SPACESHIP_CI)
    if value.is_fixnum(cmp):
        c = value.fix2int(cmp)
        if mid == helpers.LT:
            return value.newbool(c < 0)
        if mid == helpers.LE:
            return value.newbool(c <= 0)
        if mid == helpers.GT:
            return value.newbool(c > 0)
        return value.newbool(c >= 0)
    # nil or an exotic Integer: CRuby's own operator raises the ArgumentError.
    gcroots.hold(recv)
    gcroots.hold(arg)
    try:
        return rubycall.call(recv, mid, [arg])
    finally:
        gcroots.release(arg)
        gcroots.release(recv)


def _encoding_find(frame, recv, recv_at):
    name_v = frame.stack[recv_at + 1]
    if value.is_immediate(name_v) or not boot.is_string(name_v):
        return value.Q_UNDEF
    name = boot.str_of(name_v)
    if name in enc_cache:
        _drop(frame, recv_at)
        debug.count_native()
        return enc_cache[name]
    _drop(frame, recv_at)
    v = rubycall.call(recv, ENC_FIND, [name_v])
    enc_cache[name] = v
    return v


class _VMCore(object):
    # Quasi-immutable: a prebuilt plain field would fold to its pre-boot 0.
    _immutable_fields_ = ['value?']

    def __init__(self):
        self.value = 0


vm_core = _VMCore()


@dont_look_inside
def _vm_core():
    """RubyVM::FrozenCore, receiver of core# (vm_insnhelper.c:5668)."""
    if vm_core.value == 0:
        v = boot.vm_core()
        boot.gc_register(v)
        vm_core.value = v
    return vm_core.value


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.sends import invoke
from rpyyarv.interp.blocks import call_block
from rpyyarv.interp.throws import MAX_SCOPES
from rpyyarv.interp.stackops import _drop
