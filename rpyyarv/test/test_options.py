import pytest

from rpyyarv import debug
from rpyyarv import options
from rpyyarv.error import RPyYarvError


def test_jit_options_are_consumed_before_forwarding_ruby_arguments(monkeypatch):
    calls = []
    driver = object()
    monkeypatch.setattr(options, 'set_user_param',
                        lambda *args: calls.append(args))
    ruby_args = ['--disable-gems', 'script.rb', '--jit', 'script argument']
    argv = ['vm', '--jit', 'max_unroll_recursion=14,trace_limit=10000',
            '--jit', 'default'] + ruby_args
    assert options.configure_options(argv, driver) == ['vm'] + ruby_args
    assert calls == [(driver, 'max_unroll_recursion=14,trace_limit=10000'),
                     (driver, 'default')]
    assert options.configure_options(['vm'] + ruby_args, driver) == ['vm'] + ruby_args


@pytest.mark.parametrize('option', ['--jit', '--debug'])
def test_missing_parameters(option):
    with pytest.raises(RPyYarvError) as info:
        options.configure_options(['vm', option], object())
    assert 'requires a parameter string' in info.value.msg


def test_debug_and_jit_options_can_be_combined(monkeypatch):
    calls = []
    monkeypatch.setattr(options, 'set_user_param',
                        lambda driver, text: calls.append(text))
    argv = ['vm', '--debug', 'stack,insn', '--jit', 'max_unroll_recursion=14',
            'script.rb', '--debug', 'script argument']
    assert options.configure_options(argv, object()) == [
        'vm', 'script.rb', '--debug', 'script argument']
    assert debug.on(debug.STACK) and debug.on(debug.INSN)
    assert calls == ['max_unroll_recursion=14']


def test_debug_environment_no_longer_enables_tracing(monkeypatch):
    monkeypatch.setenv('RPYYARV_DEBUG', 'all')
    options.configure_options(['vm', 'script.rb'], object())
    assert not debug.state.enabled


def test_unknown_debug_channel_is_reported(monkeypatch):
    messages = []
    monkeypatch.setattr(debug, 'write', messages.append)
    options.configure_options(['vm', '--debug', 'stack,unknown', 'script.rb'],
                              object())
    assert debug.on(debug.STACK)
    assert 'unknown --debug channel unknown' in ''.join(messages)


@pytest.mark.parametrize('error', [ValueError, options.TraceLimitTooHigh])
def test_invalid_jit_parameters_are_reported(monkeypatch, error):
    def invalid(driver, text):
        raise error()
    monkeypatch.setattr(options, 'set_user_param', invalid)
    with pytest.raises(RPyYarvError) as info:
        options.configure_options(['vm', '--jit', 'bad=value'], object())
    assert '--jit' in info.value.msg
