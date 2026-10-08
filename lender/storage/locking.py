from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

from ..domain.errors import StorageError
from .paths import DataPaths

LOCK_TIMEOUT = 5.0
LOCK_POLL_INTERVAL = 0.02

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


def _lock(fd: int) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    if msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    raise StorageError(
        "this platform provides no file locking, so the store cannot be shared safely"
    )


def _unlock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def store_lock(paths: DataPaths, timeout: float | None = None) -> Iterator[None]:
    wait = LOCK_TIMEOUT if timeout is None else timeout
    try:
        fd = os.open(paths.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise StorageError(f"cannot open the store lock file {paths.lock_file}: {exc}") from exc
    try:
        deadline = time.monotonic() + wait
        while not _lock(fd):
            if time.monotonic() >= deadline:
                raise StorageError(
                    f"the data directory {paths.root} is in use by another lender "
                    f"process; waited {wait:g}s, try again"
                )
            time.sleep(LOCK_POLL_INTERVAL)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
