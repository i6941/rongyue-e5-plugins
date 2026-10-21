"""Minimal cross-platform ``fcntl`` stand-in for running the device tests off-device.

The plugin backends (``plugins/*/control.py``) run as root on the E5's
OpenWrt and use ``fcntl.flock`` to serialise access to their run directories.
``fcntl`` is Unix-only, so importing those modules fails outright on Windows
and macOS.

This stub provides just enough of the module for the unit tests to import and
exercise the pure-Python logic. The device always has the real thing; nothing
here is shipped to the device.
"""
import os
import sys

LOCK_EX = 2
LOCK_SH = 1
LOCK_NB = 4
LOCK_UN = 8

__all__ = [
    "LOCK_EX",
    "LOCK_SH",
    "LOCK_NB",
    "LOCK_UN",
    "flock",
    "lockf",
]

# When this module is installed as ``sys.modules['fcntl']``, importing fcntl
# again would resolve to ourselves and recurse forever. Look the real module
# up in sys.modules under its original name and only fall back to a no-op.
_REAL = sys.modules.get("fcntl")
if _REAL is not None and getattr(_REAL, "__name__", "") == "fcntl" and _REAL is not sys.modules.get(__name__):
    _REAL = None


def flock(fd, operation):
    """Best-effort advisory lock.

    On platforms with real ``flock`` this is a no-op wrapper because the test
    suite only needs the call to succeed, not to provide mutual exclusion
    between concurrent writers.
    """
    if _REAL is None:
        return None
    return _REAL.flock(fd, operation)


def lockf(fd, operation, length=0, start=0, whence=0):
    """Best-effort record lock; see :func:`flock`."""
    if _REAL is None:
        return None
    return _REAL.lockf(fd, operation, length, start, whence)
