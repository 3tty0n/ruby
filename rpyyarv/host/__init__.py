"""The host CRuby: RPYYARV_BUILD picks it, host/<tag>/ describes it.

Everything version-specific that RPyYARV compiles in comes from here:
host/<tag>/insns.py (rpyvmgen, from insns.def) and host/<tag>/consts.py
(hostconsts.c, from the host's headers). `make host` writes both.
"""
import importlib
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_RPYYARV = os.path.dirname(_HERE)

BUILD = os.environ.get('RPYYARV_BUILD') or os.path.join(
    os.path.dirname(_RPYYARV), 'build')


def _source_dir(build):
    """The build's srcdir: generated headers (prism, id.h) land there too."""
    try:
        with open(os.path.join(build, 'Makefile')) as f:
            m = re.search(r'^srcdir\s*=\s*(.*?)\s*$', f.read(), re.M)
    except IOError:
        m = None
    if m is None:
        return os.path.dirname(_RPYYARV)
    return os.path.normpath(os.path.join(build, m.group(1)))


SRC = _source_dir(BUILD)


def _api_version(src):
    with open(os.path.join(src, 'include', 'ruby', 'version.h')) as f:
        text = f.read()
    return tuple(int(re.search(r'define RUBY_API_VERSION_%s\s+(\d+)' % k,
                               text).group(1)) for k in ('MAJOR', 'MINOR'))


VERSION = _api_version(SRC)
TAG = 'v%d_%d' % VERSION


def load(name):
    """host/<TAG>/<name>.py's public names, for a stub module to re-export."""
    try:
        mod = importlib.import_module('rpyyarv.host.%s.%s' % (TAG, name))
    except ImportError:
        raise ImportError('no host description %s/%s.py for ruby %d.%d at %s;'
                          ' run `make -C rpyyarv host`'
                          % (TAG, name, VERSION[0], VERSION[1], SRC))
    return dict((k, v) for k, v in vars(mod).items()
                if not k.startswith('__'))
