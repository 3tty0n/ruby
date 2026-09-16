"""Unit tests for the debug channels: tracing, iseq dumps, the summary."""

import os

import debug
import insns
import interp
import loader
import symbols
from frame import Frame
from iseq import W_CallInfo, W_ISeq, NO_BLOCK_ISEQ
from objects.main import W_Main
from objects.string import W_String
from objects.transparent import W_Fixnum
from support import fixture, traced


def run_fixture(name):
    return lambda: interp.run(loader.load_dump(fixture(name)))


def test_off_by_default():
    debug.reset()
    assert not debug.state.enabled
    assert not debug.on(debug.INSN)


def test_configure_names_channels():
    debug.reset()
    assert debug.configure('insn, call') == []
    assert debug.state.enabled
    assert debug.on(debug.INSN)
    assert debug.on(debug.CALL)
    assert not debug.on(debug.STACK)
    debug.reset()


def test_configure_all_and_unknown():
    debug.reset()
    assert debug.configure('all') == []
    for bit in (debug.INSN, debug.STACK, debug.CALL, debug.ISEQ,
                debug.SUMMARY):
        assert debug.on(bit)
    debug.reset()
    assert debug.configure('insn,bogus,') == ['bogus']
    assert debug.on(debug.INSN)
    debug.reset()


def test_configure_from_env():
    debug.reset()
    saved = os.environ.get('RPYYARV_DEBUG')
    os.environ['RPYYARV_DEBUG'] = 'stack'
    try:
        assert debug.configure_from_env() == []
        assert debug.on(debug.STACK)
    finally:
        if saved is None:
            del os.environ['RPYYARV_DEBUG']
        else:
            os.environ['RPYYARV_DEBUG'] = saved
        debug.reset()


def test_disasm_decodes_every_operand_kind():
    mid = symbols.intern('each')
    w_body = W_ISeq('body', [insns.LEAVE], [], 0, 1)
    iseq = W_ISeq('<test>', [insns.PUTOBJECT, 0,
                             insns.GETLOCAL, 1,
                             insns.JUMP, 8,
                             insns.SEND, 1, NO_BLOCK_ISEQ,
                             insns.DEFINEMETHOD, mid, 2,
                             insns.LEAVE],
                  [W_String('hi'), W_CallInfo(mid, 2), w_body], 2, 4)
    text = debug.disasm(iseq)
    assert 'putobject "hi"' in text, text
    assert 'getlocal local[1]' in text, text
    assert 'jump -> 8' in text, text
    assert 'send <W_CallInfo each argc=2>, no block' in text, text
    assert 'definemethod each, <W_ISeq body>' in text, text
    # The nested ISeq follows its parent
    assert text.index('== body') > text.index('== <test>'), text


def test_disasm_header_reports_shape():
    iseq = W_ISeq('m', [insns.LEAVE], [], 3, 7, nparams=2)
    assert '== m (3 local(s), stack 7, 2 param(s))' in debug.disasm(iseq)


def test_iseq_channel_dumps_before_running():
    text = traced('iseq', run_fixture('fib_rec.iseq'))
    assert '== <main>' in text
    assert '== fib' in text
    assert 'opt_send_without_block <W_CallInfo fib argc=1>' in text


def test_insn_channel_traces_dispatch():
    iseq = W_ISeq('<test>', [insns.PUTOBJECT, 0, insns.LEAVE],
                  [W_Fixnum(7)], 0, 1)

    def go():
        interp.execute(iseq, Frame(iseq, W_Main()))
    lines = traced('insn', go).splitlines()
    assert lines == ['   0  putobject 7', '   2  leave'], lines


def test_stack_channel_shows_operands():
    iseq = W_ISeq('<test>', [insns.PUTOBJECT, 0, insns.PUTOBJECT, 0,
                             insns.OPT_PLUS, insns.LEAVE],
                  [W_Fixnum(2)], 0, 2)

    def go():
        interp.execute(iseq, Frame(iseq, W_Main()))
    # The stack is reported as the instruction on the same line sees it
    assert 'stack [2, 2]' in traced('stack', go)


def test_call_channel_brackets_each_call():
    text = traced('call', run_fixture('locals.iseq'))
    assert '-> f(9, 4)' in text, text
    assert '<- f = 5' in text, text


def test_call_channel_covers_builtins():
    text = traced('call', run_fixture('fib.iseq'))
    assert '-> puts(' in text, text
    assert '<- puts = nil' in text, text


def test_call_depth_indents_the_trace():
    text = traced('insn,call', run_fixture('locals.iseq'))
    assert '\n     0  getlocal local[0]' in text, text


def test_summary_counts_every_instruction():
    lines = traced('summary', run_fixture('fib_rec.iseq')).splitlines()
    assert lines[0].startswith('== '), lines[0]
    assert lines[0].endswith(' instruction(s) executed'), lines[0]
    counts = []
    for line in lines[1:]:
        counts.append(int(line.split()[0]))
    assert counts == sorted(counts, reverse=True), counts
    assert sum(counts) == int(lines[0].split()[1]), lines[0]


def test_nothing_written_when_off():
    assert traced('', run_fixture('fib_rec.iseq')) == ''


def test_note_writes_unconditionally():
    out = []
    saved = debug.write
    debug.write = lambda s: out.append(s)
    try:
        debug.reset()
        debug.note('hello')
    finally:
        debug.write = saved
    assert out == ['[rpyyarv] hello\n'], out
