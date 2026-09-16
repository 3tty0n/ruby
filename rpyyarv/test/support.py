"""Helpers for writing RPyYARV unit tests.

`asm` builds an ISeq by hand, `run` executes one, and `expect_unsupported`
asserts on the message RPyYARV gives when it meets something it cannot do.
Together they are enough to test an instruction, a builtin or an object
without going through Ruby source at all.
"""

import os
import shutil
import subprocess
import tempfile

import debug
import interp
import kernel
import loader
from error import UnsupportedOperation
from frame import Frame
from iseq import W_ISeq
from objects.main import W_Main

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.environ.get('RPYYARV_BUILD',
                       os.path.join(os.path.dirname(ROOT), 'build'))
DUMPER = os.path.join(ROOT, 'scripts', 'dump_iseq.rb')


def ruby_exe():
    """This tree's ruby as (exe, env); only it matches insns.py.

    Returns (None, why) when it is missing or will not run, so a caller can
    skip rather than fail.
    """
    exe = os.environ.get('RUBY', os.path.join(BUILD, 'ruby'))
    if not os.path.exists(exe):
        return None, 'no ruby in %s; build CRuby first' % BUILD
    env = dict(os.environ)
    # The build tree's libruby is tagged with its install prefix, not its path
    for var in ('DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
        env[var] = os.pathsep.join([BUILD] + [p for p in [env.get(var)] if p])
    try:
        subprocess.check_output([exe, '-e', ''], env=env,
                                stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as e:
        return None, '%s will not run: %s' % (exe, e)
    return exe, env


def compile_rb(path, ruby=None):
    """Compiles a .rb to the ISeq dump text load_dump() reads."""
    exe, env = ruby if ruby else ruby_exe()
    text = subprocess.check_output([exe, DUMPER, path], env=env)
    if not isinstance(text, str):
        text = text.decode('utf-8')
    return text


def asm(consts, nlocals, stack_max, items, name='<test>', nparams=0,
        simple_params=True):
    """Tiny assembler. In items, ':name' defines a label and takes no space;
    any other string references one and occupies a slot."""
    labels = {}
    pos = 0
    for item in items:
        if isinstance(item, str) and item.startswith(':'):
            labels[item[1:]] = pos
        else:
            pos += 1
    code = []
    for item in items:
        if isinstance(item, str):
            if item.startswith(':'):
                continue
            code.append(labels[item])
        else:
            code.append(item)
    return W_ISeq(name, code, consts, nlocals, stack_max, nparams,
                  simple_params)


def compile_source(source, ruby=None):
    """Compiles Ruby source text to an ISeq dump, through a temp file."""
    tmp = tempfile.mkdtemp(prefix='rpyyarv-')
    try:
        path = os.path.join(tmp, 'program.rb')
        f = open(path, 'w')
        try:
            f.write(source)
        finally:
            f.close()
        return compile_rb(path, ruby)
    finally:
        shutil.rmtree(tmp)


def run(w_iseq, w_self=None):
    """Runs on a self of its own, so tests cannot see each other."""
    if w_self is None:
        w_self = W_Main()
    return interp.execute(w_iseq, Frame(w_iseq, w_self))


def run_dump(text, w_self=None):
    """Loads an ISeq dump -- see the `compile_rb` fixture -- and runs it."""
    return run(loader.load_dump(text), w_self)


def expect_unsupported(w_iseq, w_self, msg):
    try:
        run(w_iseq, w_self)
    except UnsupportedOperation as e:
        assert e.msg == msg, 'got %r, expected %r' % (e.msg, msg)
    else:
        raise AssertionError('expected UnsupportedOperation: %s' % msg)


def capture(func):
    """Collect what the builtins print instead of writing to stdout."""
    out = []
    saved = kernel.write
    kernel.write = lambda s: out.append(s)
    try:
        w_ret = func()
    finally:
        kernel.write = saved
    return ''.join(out), w_ret


def traced(channels, thunk):
    """Runs thunk with the debug channels on, returning what debug wrote."""
    out = []
    saved_puts = kernel.write
    debug.reset()
    debug.configure(channels)
    debug.write = out.append
    kernel.write = lambda s: None
    try:
        thunk()
    finally:
        kernel.write = saved_puts
        debug.reset()
    return ''.join(out)


def fixture(name):
    """Reads a recorded file from test/, e.g. fixture('fib.iseq')."""
    f = open(os.path.join(HERE, name))
    try:
        return f.read()
    finally:
        f.close()
