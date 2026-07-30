import os

import interp
import loader


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
    if len(argv) != 2:
        print 'usage: %s FILE.iseq' % argv[0]
        return 1
    interp.run(loader.load_dump(read_file(argv[1])))
    return 0


def target(driver, args):
    return entry_point, None
