"""Parameter binding for method and block calls."""
from __future__ import absolute_import

from rpyyarv import boot
from rpyyarv import gcroots
from rpyyarv import rubycall
from rpyyarv import symbols
from rpyyarv import value
from rpyyarv.error import RubyException, UnsupportedOperation
from rpyyarv.rlib import dont_look_inside, unroll_safe

# Prebuilt, so len() of it folds to 0 wherever a call passes no keywords.
NO_KEYWORDS = []


def _declare_locals(names):
    parts = []
    for name in names:
        parts.append('%s = %s' % (name, name))
    return '; '.join(parts) + '\n'


def _slot_named(w_iseq, name):
    names = w_iseq.local_names
    i = 0
    while i < len(names):
        if names[i] == name:
            return i
        i += 1
    return -1


def _refuse_iseq(w_iseq, mid):
    if w_iseq.unsupported != '':
        raise UnsupportedOperation("method '%s': %s"
                                   % (symbols.name_of(mid),
                                      w_iseq.unsupported))


@unroll_safe
def setup_params(w_iseq, callee, args, is_block, kw_names=NO_KEYWORDS,
                 kw_splat=False):
    """setup_parameters_complex; answers the opt table's pc (vm_args.c:906)."""
    nkw = len(kw_names)
    takes_kw = len(w_iseq.kw_table) > 0 or w_iseq.kwrest >= 0
    held_flagged = 0
    held_ary = 0
    # A **splat's Hash is the last argument; empty vanishes (vm_args.c:673).
    splat_hash = 0
    if kw_splat:
        splat_hash = args[len(args) - 1]
        empty = (splat_hash == value.Q_NIL
                 or rubycall.hash_size(splat_hash) == 0)
        if takes_kw or empty:
            end = len(args) - 1
            assert end >= 0
            args = args[:end]
        if not takes_kw or empty:
            splat_hash = 0
        if w_iseq.r2k and not takes_kw and not empty:
            # ruby2_keywords: the kw hash rides the rest array, flagged.
            end = len(args) - 1
            assert end >= 0
            flagged = boot.kw_hash_dup(args[end])
            # Fresh, and an RPython list is no GC root: held until bound.
            gcroots.hold(flagged)
            held_flagged = flagged
            args = args[:end]
            args.append(flagged)
    # No kw params: CRuby folds them to a trailing Hash (args_kw_argv_to_hash).
    fold = nkw > 0 and not takes_kw
    lead = w_iseq.nparams
    opt_num = len(w_iseq.opt_table) - 1
    if opt_num < 0:
        opt_num = 0
    post_num = w_iseq.post_num
    rest = w_iseq.rest_start
    post_start = w_iseq.post_start
    # Restated so the codewriter sees every index as non-negative.
    assert lead >= 0
    assert post_num >= 0
    # vm_args.c:594; a rest parameter makes the maximum unlimited.
    min_argc = lead + post_num
    max_argc = -1 if rest >= 0 else min_argc + opt_num
    n = len(args) - nkw
    if fold:
        n += 1
    if n < min_argc:
        if not is_block:
            _arity_error(n, min_argc, max_argc)
    elif max_argc >= 0 and n > max_argc:
        if not is_block:
            _arity_error(n, min_argc, max_argc)
        # arg_setup_block truncates instead of raising (vm_args.c:884).
        n = max_argc

    # After the arity check: nothing may raise between hold and release.
    kw_hash = 0
    if fold:
        args = _kw_to_positional(args, kw_names)
        end = len(args) - 1
        assert end >= 0
        if w_iseq.r2k:
            # ruby2_keywords: the folded hash carries the forwarding flag.
            args[end] = boot.kw_hash_dup(args[end])
        kw_hash = args[end]
        gcroots.hold(kw_hash)
        kw_names = NO_KEYWORDS
        nkw = 0

    i = 0
    while i < lead:
        if i < n:
            callee.local_set(i, args[i])
        else:
            callee.local_set(i, value.Q_NIL)
        i += 1

    given = n - min_argc
    if given < 0:
        given = 0
    filled = given if given < opt_num else opt_num
    i = 0
    while i < filled:
        callee.local_set(lead + i, args[lead + i])
        i += 1

    if rest >= 0:
        count = given - filled
        values = [0] * count
        i = 0
        while i < count:
            values[i] = args[lead + filled + i]
            i += 1
        # The caller's frame holds these while the shim copies them.
        ary = rubycall.ary_new(values)
        # The callee is not on the mark chain yet; only this hold roots it.
        gcroots.hold(ary)
        held_ary = ary
        assert rest >= 0
        callee.local_set(rest, ary)

    if post_num > 0:
        assert post_start >= 0
        i = 0
        while i < post_num:
            take = n - post_num + i
            if take >= 0 and take < n:
                callee.local_set(post_start + i, args[take])
            else:
                callee.local_set(post_start + i, value.Q_NIL)
            i += 1

    if kw_hash != 0:
        gcroots.release(kw_hash)

    if takes_kw:
        _setup_keywords(w_iseq, callee, args, len(args) - nkw, kw_names,
                        splat_hash)

    if held_ary != 0:
        gcroots.release(held_ary)
    if held_flagged != 0:
        gcroots.release(held_flagged)
    if opt_num > 0:
        return w_iseq.opt_table[filled]
    return 0


@unroll_safe
def _kw_to_positional(args, kw_names):
    """A callee with no keyword parameters takes them as one trailing Hash."""
    n = len(args) - len(kw_names)
    out = [0] * (n + 1)
    i = 0
    while i < n:
        out[i] = args[i]
        i += 1
    i = 0
    while i < len(kw_names):
        rubycall.sym_value(kw_names[i])
        i += 1
    h = rubycall.hash_new(len(kw_names))
    i = 0
    while i < len(kw_names):
        rubycall.hash_aset(h, rubycall.sym_value(kw_names[i]), args[n + i])
        i += 1
    out[n] = h
    return out


@unroll_safe
def _setup_keywords(w_iseq, callee, args, base, kw_names, splat_hash=0):
    """args_setup_kw_parameters: match by name, unfilled marked in kwbits."""
    table = w_iseq.kw_table
    required = w_iseq.kw_required
    start = w_iseq.kw_start
    nkw = len(kw_names)
    taken = [False] * nkw
    missing = []
    # Counts **splat keys taken, so leftovers need no walk of the Hash.
    used = 0
    bits = 0
    i = 0
    while i < len(table):
        found = -1
        j = 0
        while j < nkw:
            if not taken[j] and kw_names[j] == table[i]:
                found = j
                break
            j += 1
        given = value.Q_UNDEF
        if found >= 0:
            taken[found] = True
            given = args[base + found]
        elif splat_hash != 0:
            given = rubycall.hash_lookup(splat_hash,
                                         rubycall.sym_value(table[i]))
            if given != value.Q_UNDEF:
                used += 1
        slot = start + i
        assert slot >= 0
        if given != value.Q_UNDEF:
            callee.local_set(slot, given)
        elif i < required:
            missing.append(table[i])
        elif w_iseq.kw_defaults[i] != value.Q_UNDEF:
            callee.local_set(slot, w_iseq.kw_defaults[i])
        else:
            callee.local_set(slot, value.Q_NIL)
            bits |= 1 << (i - required)
        i += 1
    if len(missing) > 0:
        _keyword_error('missing', missing)

    if w_iseq.kwrest >= 0:
        j = 0
        while j < nkw:
            rubycall.sym_value(kw_names[j])
            j += 1
        if splat_hash != 0:
            rest = _splat_leftovers(w_iseq, splat_hash, used)
        else:
            rest = rubycall.hash_new(nkw)
        j = 0
        while j < nkw:
            if not taken[j]:
                rubycall.hash_aset(rest, rubycall.sym_value(kw_names[j]),
                                   args[base + j])
            j += 1
        slot = w_iseq.kwrest
        assert slot >= 0
        callee.local_set(slot, rest)
    else:
        unknown = []
        j = 0
        while j < nkw:
            if not taken[j]:
                unknown.append(kw_names[j])
            j += 1
        if len(unknown) > 0:
            _keyword_error('unknown', unknown)
        if splat_hash != 0 and used != rubycall.hash_size(splat_hash):
            _splat_unknown(w_iseq, splat_hash, used)

    if w_iseq.kw_bits >= 0:
        slot = w_iseq.kw_bits
        assert slot >= 0
        callee.local_set(slot, value.int2fix(bits))


@dont_look_inside
def _splat_leftovers(w_iseq, splat_hash, used):
    """The **splat's keys that no declared keyword parameter took."""
    rest = rubycall.hash_resurrect(splat_hash)
    if used > 0:
        for mid in w_iseq.kw_table:
            rubycall.hash_delete(rest, rubycall.sym_value(mid))
    return rest


@dont_look_inside
def _splat_unknown(w_iseq, splat_hash, used):
    keys = rubycall.hash_keys(_splat_leftovers(w_iseq, splat_hash, used))
    raise RubyException(rubycall.keyword_error('unknown', keys),
                        'ArgumentError')


@dont_look_inside
def _keyword_error(kind, names):
    keys = []
    for mid in names:
        keys.append(rubycall.sym_value(mid))
    raise RubyException(
        rubycall.keyword_error(kind, rubycall.ary_new(keys)), 'ArgumentError')


@dont_look_inside
def _arity_error(given, min_argc, max_argc):
    raise RubyException(boot.arity_error(given, min_argc, max_argc),
                        'ArgumentError')


def _iseq_arity(w_iseq):
    """rb_proc_arity (proc.c:1120): min when fixed, -(min+1) otherwise."""
    opt_num = len(w_iseq.opt_table) - 1
    if opt_num < 0:
        opt_num = 0
    has_kw = len(w_iseq.kw_table) > 0 or w_iseq.kwrest >= 0
    min_argc = w_iseq.nparams + w_iseq.post_num \
        + (1 if w_iseq.kw_required > 0 else 0)
    if w_iseq.rest_start >= 0:
        return -min_argc - 1
    max_argc = w_iseq.nparams + opt_num + w_iseq.post_num \
        + (1 if has_kw else 0)
    return min_argc if min_argc == max_argc else -min_argc - 1
