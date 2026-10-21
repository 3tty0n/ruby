from rpyyarv import debug

from rpyyarv.error import RPyYarvError
from rpyyarv.rlib import TraceLimitTooHigh, set_user_param


def configure_options(argv, driver):
    index = 1
    while index < len(argv):
        option = argv[index]
        if option != '--jit' and option != '--debug':
            break
        if index + 1 == len(argv):
            raise RPyYarvError(option + ' requires a parameter string')
        text = argv[index + 1]
        if option == '--debug':
            for name in debug.configure(text):
                debug.note('unknown --debug channel %s; known: %s'
                           % (name, debug.CHANNELS))
        else:
            try:
                set_user_param(driver, text)
            except ValueError:
                raise RPyYarvError('invalid --jit parameters: ' + text)
            except TraceLimitTooHigh:
                raise RPyYarvError('--jit trace_limit exceeds the trace encoder limit')
        index += 2
    return [argv[0]] + argv[index:]
