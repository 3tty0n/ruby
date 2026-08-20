"""Blocks, procs and their handles."""
from __future__ import absolute_import

from rpyyarv import block as block_mod
from rpyyarv import boot
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import UnsupportedOperation
from rpyyarv.frame import Frame
from rpyyarv.rlib import dont_look_inside, promote, raw_word, unroll_safe

from rpyyarv.interp.consts_ids import AREF, ARITY, CALL, EQQ_, LAMBDA_P, TO_PROC, YIELD
from rpyyarv.interp.args import NO_KEYWORDS, _iseq_arity, _kw_to_positional, setup_params

class _Blocks(object):
    """Blocks C refers to by integer handle only: RPython's GC moves objects."""
    def __init__(self):
        self.table = []         # handle -> W_Block, None for a free slot
        # handle -> the self it was handed over under, for instance_eval yields.
        self.selves = []
        self.free = []          # handles whose GC owner died
        self.by_proc = {}       # a materialised Proc -> the block behind it
        self.error = None       # an RPython error the callback could not raise
        self.exc = None         # likewise, a Ruby exception
        self.jump = None        # likewise, a break or a non-local return


blocks = _Blocks()


def _alloc_handle(w_block):
    # Slots come back only when their GC owner died, so stored blocks live.
    while True:
        h = boot.pop_dead_handle()
        if h < 0:
            break
        _release_handle(h)
    # The sentinel, not the live receiver: a real rebind must never collide.
    here = boot.block_sentinel()
    if len(blocks.free) > 0:
        h = blocks.free.pop()
        blocks.table[h] = w_block
        blocks.selves[h] = here
        return h
    blocks.table.append(w_block)
    blocks.selves.append(here)
    return len(blocks.table) - 1


def _release_handle(h):
    w_block = blocks.table[h]
    if w_block is not None:
        v = w_block.proc_value
        # The Proc died; a later escape must build a fresh one.
        w_block.proc_value = 0
        if v in blocks.by_proc and blocks.by_proc[v] is w_block:
            del blocks.by_proc[v]
    blocks.table[h] = None
    blocks.selves[h] = 0
    blocks.free.append(h)


@dont_look_inside
def _to_proc(w_block):
    """A real Proc for an escaping block (vm_insnhelper.c:543), memoised."""
    if w_block is None:
        return value.Q_NIL
    if w_block.proc_value != 0:
        return w_block.proc_value
    v = boot.proc_new(_alloc_handle(w_block))
    w_block.proc_value = v
    blocks.by_proc[v] = w_block
    return v


def _proc_block_of(recv):
    """The live block a proxyable receiver stands for; the proc itself says.
    A by_proc lookup could hit a stale entry once the address was recycled."""
    if value.is_immediate(recv) or \
            (raw_word(recv, value.FLAGS_WORD) & value.T_MASK) != value.T_DATA:
        return None
    h = boot.proc_handle(recv)
    if h < 0 or h >= len(blocks.table):
        return None
    return blocks.table[h]


def _is_proxy_call(mid):
    """The proxy runs the block itself for these; anything else needs a Proc."""
    return mid == CALL or mid == YIELD or mid == AREF or mid == EQQ_


@dont_look_inside
def _block_from_value(frame_block, v):
    """The block a &arg site passes on (vm_args.c:1116); takes no frame."""
    if v == value.Q_NIL:
        return None
    if v == proxy.value:
        # The frame's own block, without ever having built a Proc for it.
        return frame_block
    if v in blocks.by_proc:
        return blocks.by_proc[v]
    if boot.is_symbol(v):
        return block_mod.from_symbol(symbols.intern(boot.sym_of(v)))
    if not value.is_immediate(v) and boot.is_proc(v):
        return block_mod.from_proc(v)
    # vm_to_proc, vm_args.c:1044.
    p = rubycall.call0(v, TO_PROC)
    if value.is_immediate(p) or not boot.is_proc(p):
        raise UnsupportedOperation(
            'a &block argument that is not a Proc, a Symbol or nil and whose '
            '#to_proc did not answer a Proc is not supported')
    return block_mod.from_proc(p)


@unroll_safe
def _block_send(frame, mid, recv_at, argc, w_block,
                kw_names=NO_KEYWORDS, kw_splat=False):
    """A send onto a block RPyYARV holds: the proxy (compile.c:9564) or Proc."""
    args = [0] * argc
    i = 0
    while i < argc:
        args[i] = frame.stack[recv_at + 1 + i]
        i += 1
    _drop(frame, recv_at)
    return _block_send_args(mid, w_block, args, kw_names, kw_splat)


@unroll_safe
def _block_send_args(mid, w_block, args, kw_names=NO_KEYWORDS,
                     kw_splat=False):
    if _is_proxy_call(mid):
        if w_block is None:
            raise UnsupportedOperation('the block parameter is nil')
        return call_block(w_block, args, kw_names, kw_splat)
    if w_block is not None and w_block.kind == block_mod.KIND_ISEQ \
            and len(args) == 0 and len(kw_names) == 0 and not kw_splat:
        # The Proc wraps a C yielder, so these come from the ISeq it stands for.
        if mid == ARITY:
            return value.int2fix(_iseq_arity(w_block.w_iseq))
        if mid == LAMBDA_P:
            return value.newbool(w_block.is_lambda)
    if len(kw_names) > 0:
        args = _kw_to_positional(args, kw_names)
    if len(kw_names) > 0 or kw_splat:
        return rubycall.call_kw(_to_proc(w_block), mid, args)
    return rubycall.call(_to_proc(w_block), mid, args)


@unroll_safe
def call_block(w_block, args, kw_names=NO_KEYWORDS, kw_splat=False,
               self_val=value.Q_UNDEF, cref=None, entry_override=None):
    """Run a block's ISeq in a frame chaining to the defining one's locals."""
    keyed = len(kw_names) > 0 or kw_splat
    if w_block.kind != block_mod.KIND_ISEQ:
        if keyed:
            return _call_foreign_block_kw(w_block, args, kw_names, kw_splat)
        return _call_foreign_block(w_block, args)
    # Promoted here: the frame's arrays then take constant sizes.
    b_iseq = promote(w_block.w_iseq)
    outer = w_block.frame
    if self_val == value.Q_UNDEF:
        self_val = outer.self_val
    if cref is None:
        cref = outer.cref
    entry = entry_override if entry_override is not None else outer.entry
    callee = Frame(b_iseq, self_val, cref, entry)
    callee.defining_frame = outer
    callee.block = w_block.outer
    callee.own_block = w_block
    if w_block.is_lambda:
        return _run_lambda(w_block, b_iseq, callee, args, kw_names, kw_splat)
    if b_iseq.autosplat and len(args) == 1 and not keyed:
        args = _autosplat(args)
    pc = 0
    if b_iseq.simple_params and not keyed:
        n = len(args)
        if n > b_iseq.nparams:
            n = b_iseq.nparams
        i = 0
        while i < n:
            callee.local_set(i, args[i])
            i += 1
    else:
        pc = setup_params(b_iseq, callee, args, True, kw_names, kw_splat)
    try:
        return execute(b_iseq, callee, pc)
    except block_mod.BlockNext, e:
        return e.value


@unroll_safe
def _run_lambda(w_block, b_iseq, callee, args, kw_names, kw_splat):
    """arg_setup_method: exact arity, no autosplat (vm_insnhelper.c:1832)."""
    pc = setup_params(b_iseq, callee, args, False, kw_names, kw_splat)
    try:
        return execute(b_iseq, callee, pc)
    except block_mod.BlockNext, e:
        return e.value
    except block_mod.BlockReturn, e:
        if e.frame is not callee:
            raise
        return e.value
    except block_mod.BlockBreak, e:
        if e.w_block is not w_block:
            raise
        return e.value
    finally:
        # A later return aimed here is the orphaned LocalJumpError.
        callee.dead = True


@unroll_safe
def _run_bmethod(entry, recv, args, kw_names=NO_KEYWORDS, kw_splat=False):
    """entry.w_block: method-style arity; return/break leave the method."""
    w_block = entry.w_block
    b_iseq = promote(w_block.w_iseq)
    outer = w_block.frame
    # The method's own identity, not the defining frame's: super needs it.
    callee = Frame(b_iseq, recv, outer.cref, entry)
    callee.defining_frame = outer
    callee.own_block = w_block
    return _run_lambda(w_block, b_iseq, callee, args, kw_names, kw_splat)


@dont_look_inside
def _call_foreign_block_kw(w_block, args, kw_names, kw_splat):
    """Keywords as the one trailing Hash RB_PASS_KEYWORDS names."""
    if w_block.kind != block_mod.KIND_PROC:
        raise UnsupportedOperation('a &:symbol block takes no keywords')
    if not kw_splat:
        args = _kw_to_positional(args, kw_names)
    elif len(args) > 0 and args[len(args) - 1] == value.Q_NIL:
        end = len(args) - 1
        assert end >= 0
        return rubycall.call(w_block.proc_value, CALL, args[:end])
    return rubycall.call_kw(w_block.proc_value, CALL, args)


@dont_look_inside
def _call_foreign_block(w_block, args):
    """A foreign block: a CRuby Proc, or &:sym (vm_insnhelper.c:552)."""
    if w_block.kind == block_mod.KIND_PROC:
        return rubycall.call(w_block.proc_value, CALL, args)
    if len(args) == 0:
        raise UnsupportedOperation('a &:symbol block needs a receiver')
    rest = []
    i = 1
    while i < len(args):
        rest.append(args[i])
        i += 1
    return rubycall.call(args[0], w_block.mid, rest)


@dont_look_inside
def _autosplat(args):
    """TODO: CRuby asks to_ary (vm_args.c:863); this takes a real Array."""
    v = args[0]
    if value.is_immediate(v):
        return args
    if value.is_plain_array(v):
        # Read in place: a call per element showed up in the profile.
        n = value.ary_len(v)
        out = [0] * n
        i = 0
        while i < n:
            out[i] = value.ary_at(v, i)
            i += 1
        return out
    if not boot.is_array(v):
        return args
    n = boot.ary_len(v)
    out = [0] * n
    i = 0
    while i < n:
        out[i] = boot.ary_entry(v, i)
        i += 1
    return out


@unroll_safe
def _outer_frame(frame, level):
    """The frame `level` up the chain; its locals are heap (shares_locals)."""
    f = frame
    i = 0
    while i < level:
        f = f.defining_frame
        if f is None:
            raise UnsupportedOperation(
                'a local at level %d has no enclosing scope in %s (%s)'
                % (level, frame.w_iseq.name, frame.w_iseq.path))
        i += 1
    return f


@unroll_safe
def invoke_block(frame, w_ci):
    w_block = frame.block
    if w_block is None:
        raise UnsupportedOperation('yield without a block')
    argc = w_ci.argc
    at = frame.sp - argc
    if at < 0:
        raise UnsupportedOperation(
            'yield with %d argument(s) underflows the stack' % argc)
    if w_ci.kw_splat:
        _kw_splat_hash(frame, at + argc - 1)
    if w_ci.splat:
        trailing = 1 if w_ci.kw_splat else len(w_ci.kw_names)
        args = _splat_args(frame, at, argc - trailing, trailing)
    else:
        args = [0] * argc
        i = 0
        while i < argc:
            args[i] = frame.stack[at + i]
            i += 1
    _drop(frame, at)
    return call_block(w_block, args, w_ci.kw_names, w_ci.kw_splat)


# Bottom import: breaks the cycle. By the time a sibling's
# own bottom import asks this module for a name, everything
# above is already bound.
from rpyyarv.interp.builtins import proxy
from rpyyarv.interp.sends import _kw_splat_hash, _splat_args
from rpyyarv.interp.stackops import _drop
from rpyyarv.interp.execute import execute
