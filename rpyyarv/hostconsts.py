"""The host's header constants, host/<tag>/consts.py (from hostconsts.c)."""
from rpyyarv import host

globals().update(host.load('consts'))
