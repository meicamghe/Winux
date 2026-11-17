"""Cross-process synchronization for mutations of a managed Wine prefix."""

import fcntl
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path


def _private_lock_directory():
    path = Path.home() / ".local/share/winux/locks"
    absolute = Path(os.path.abspath(path))
    for component in reversed((absolute, *absolute.parents)):
        if component.is_symlink():
            raise ValueError(f"Prefix lock directory contains a symlink: {component}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for component in reversed((absolute, *absolute.parents)):
        if component.is_symlink():
            raise ValueError(f"Prefix lock directory contains a symlink: {component}")
    if not path.is_dir():
        raise ValueError("Prefix lock path is not a directory")
    os.chmod(path, 0o700)
    return path


@contextmanager
def prefix_operation_lock(prefix_name, *, blocking=True):
    """Hold the canonical per-prefix lock shared by all mutating operations.

    This advisory lock coordinates Winux processes only. Callers needing a
    quiescent prefix must separately detect unmanaged Wine processes.
    """
    if not isinstance(prefix_name, str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,64}", prefix_name
    ):
        raise ValueError("Invalid prefix name")

    lock_path = _private_lock_directory() / f"{prefix_name}.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Prefix lock path must be a regular file")
        os.fchmod(descriptor, 0o600)
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError as error:
            raise RuntimeError(
                f"Another operation is using prefix: {prefix_name}"
            ) from error
        yield
    finally:
        os.close(descriptor)
