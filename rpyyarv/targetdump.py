import os
import sys

# rpython puts only this dir on sys.path; add the repo root so `rpyyarv` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpyyarv import debug
from rpyyarv import interp
from rpyyarv import loader
from rpyyarv.error import RPyYarvError
from rpyyarv.options import configure_options


def read_file(path):
    fd = os.open(path, os.O_RDONLY, 0777)
    chunks = []
    while True:
        chunk = os.read(fd, 65536)
        if len(chunk) == 0:
            break
        chunks.append(chunk)
    os.close(fd)
    return ''.join(chunks)


def entry_point(argv):
    try:
        argv = configure_options(argv, interp.jitdriver)
    except RPyYarvError, e:
        print '[rpyyarv] %s' % e.msg
        return 1
    if len(argv) != 2:
        print 'usage: %s [--jit PARAM=VALUE,...] [--debug CHANNELS] FILE.iseq' % argv[0]
        return 1
    interp.run(loader.load_dump(read_file(argv[1])))
    return 0


def target(driver, args):
    return entry_point, None
