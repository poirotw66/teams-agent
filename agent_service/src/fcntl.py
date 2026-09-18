"""Windows compatibility shim for fcntl flock."""
import sys

if sys.platform == "win32":
    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def flock(fd: int, operation: int) -> None:
        pass

    def fcntl(fd: int, op: int, arg: int = 0) -> int:
        return 0
else:
    # On POSIX systems, delegate to built-in C module
    try:
        from _fcntl import *  # type: ignore[import-not-found] # noqa: F403
    except ImportError:
        pass
