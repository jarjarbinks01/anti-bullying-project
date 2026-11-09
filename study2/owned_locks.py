"""Process/thread-local ownership of actual flock handles; no caller booleans."""
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import os
from pathlib import Path
import threading

from .common import PipelineError

_held = ContextVar('study2_owned_locks', default={})


def assert_owned(path):
    path = Path(path).absolute()
    value = _held.get().get(str(path))
    if value is None or value[:2] != (os.getpid(), threading.get_ident()):
        raise PipelineError('exclusive_lock_ownership_required')
    handle = value[2]
    if handle.closed or path.is_symlink():
        raise PipelineError('exclusive_lock_identity_changed')
    a, b = os.fstat(handle.fileno()), path.stat()
    if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
        raise PipelineError('exclusive_lock_identity_changed')
    # The same open-file description is reasserted, never a second handle.
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise PipelineError('exclusive_lock_ownership_lost') from None
    return handle


@contextmanager
def exclusive(path):
    path = Path(path).absolute()
    if str(path) in _held.get():
        assert_owned(path)
        yield
        return
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise PipelineError('exclusive_lock_path_invalid')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PipelineError('exclusive_writer_busy') from None
        token = _held.set({**_held.get(), str(path): (os.getpid(), threading.get_ident(), handle)})
        try:
            assert_owned(path)
            yield
        finally:
            _held.reset(token)
            fcntl.flock(handle, fcntl.LOCK_UN)
