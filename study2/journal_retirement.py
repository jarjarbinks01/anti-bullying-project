"""Preparation-only, separately reviewed completed-journal lifecycle helper.

Only a retirement CLI; no publication, recovery, gate or selector API. The three native locks
serialize cooperating native writers. This is not a defense against an arbitrary
same-UID process ignoring locks in the final check/unlink syscall window.
"""
from contextlib import ExitStack
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

JOURNAL = 'COORDINATED_UPDATE.json'
HISTORY = 'completed-journal-history-v1'
MAX_BYTES = 1024 * 1024


class RetirementError(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise RetirementError(reason)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            getattr(info, 'st_flags', 0))


class BoundDirectory:
    """No-follow ancestor chain; all I/O is relative to held directory FDs."""
    def __init__(self, path):
        path = Path(path)
        need(path.is_absolute() and '..' not in path.parts, 'absolute_path_required')
        self.fds, self.chain = [], []
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.fds.append(fd)
            for name in path.parts[1:]:
                parent = fd
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                self.fds.append(fd)
                info = os.fstat(fd)
                self.chain.append((parent, name, fd, (info.st_dev, info.st_ino)))
            self.fd = fd
            self.check()
            need(os.fstat(fd).st_uid == os.getuid(), 'directory_owner_changed')
        except BaseException:
            self.close()
            raise

    def check(self):
        for parent, name, fd, expected in self.chain:
            a = os.stat(name, dir_fd=parent, follow_symlinks=False)
            b = os.fstat(fd)
            need(stat.S_ISDIR(a.st_mode) and stat.S_ISDIR(b.st_mode) and
                 (a.st_dev, a.st_ino) == expected == (b.st_dev, b.st_ino) and
                 a.st_uid in (0, os.getuid()) and not a.st_mode & 0o022,
                 'directory_identity_or_permissions_changed')

    def read(self, name):
        self.check()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            before = os.fstat(fd)
            need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                 before.st_uid == os.getuid() and not before.st_mode & 0o022 and
                 not getattr(before, 'st_flags', 0) & 0x40000000 and
                 before.st_size <= MAX_BYTES, 'file_metadata_invalid')
            data = bytearray()
            while len(data) <= MAX_BYTES:
                block = os.read(fd, min(65536, MAX_BYTES + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
            need(identity(before) == identity(os.fstat(fd)) and len(data) == before.st_size,
                 'file_changed_during_read')
        finally:
            os.close(fd)
        self.check()
        need(identity(before) == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False)),
             'file_identity_changed')
        return bytes(data), identity(before)

    def close(self):
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def native():
    """Use the installed package; configuration and selection are caller-bound."""
    need(sys.platform in {'darwin', 'linux'}, 'unsupported_platform')
    from . import coordinated_update as update, owned_locks, flag_binding
    need(update.JOURNAL == JOURNAL, 'unsupported_journal_name')
    return update, owned_locks, flag_binding


def exclusive_rename(directory_fd, source, destination):
    """Atomically install without replacement on macOS or Linux; fail closed."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        rename = library.renameatx_np
        flags = 4  # RENAME_EXCL
    elif sys.platform == 'linux':
        rename = getattr(library, 'renameat2', None)
        need(rename is not None, 'exclusive_rename_unavailable')
        flags = 1  # RENAME_NOREPLACE
    else:
        raise RetirementError('unsupported_platform')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(directory_fd, os.fsencode(source), directory_fd, os.fsencode(destination), flags):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def parse_completed(raw, expected_sha256, expected_side):
    need(hashlib.sha256(raw).hexdigest() == expected_sha256, 'journal_hash_mismatch')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    need(isinstance(value, dict) and value.get('format') == 'study2_coordinated_publication_journal_v1'
         and value.get('status') == 'complete', 'completed_journal_required')
    need(value.get('recovered_to', 'target') == expected_side, 'completed_outcome_mismatch')
    return value


def create_archive(directory, name, raw, fault, guard):
    """Durable temporary + platform-exclusive rename; never replace history."""
    try:
        existing, _ = directory.read(name)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        need(existing == raw, 'archive_mismatch')
        return
    temporary = '.' + name + '.pending-' + uuid.uuid4().hex
    guard()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory.fd)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            need(count > 0, 'archive_write_failed')
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    fault('archive:after_temp_sync')
    guard()
    try:
        exclusive_rename(directory.fd, temporary, name)
    except OSError as error:
        if error.errno != errno.EEXIST:
            raise
        need(directory.read(name)[0] == raw, 'archive_mismatch')
        # Keep the owned temporary as interruption evidence; never overwrite.
    fault('archive:after_install')
    guard()
    os.fsync(directory.fd)
    fault('archive:after_directory_sync')
    need(directory.read(name)[0] == raw, 'archive_mismatch')


def retire_completed(cfg, *, expected_sha256, expected_side, archive_directory, fault=None):
    """Archive exact completed bytes then unlink under all three native locks.

    Requires a caller-pinned source digest and OLD/TARGET outcome. An absent
    source retry is archive-only and explicitly NOT current tuple verification
    or permission to publish. Native verification is never mocked or replaced.
    """
    need(isinstance(expected_sha256, str) and re.fullmatch('[0-9a-f]{64}', expected_sha256)
         and expected_side in ('old', 'target'), 'explicit_expected_identity_required')
    fault = fault or (lambda phase: None)
    update, locks, binding = native()
    from .store import release_verification_cache
    state_path = Path(cfg['state_dir'])
    archive_name = expected_sha256 + '.json'
    archive_path = Path(archive_directory)
    trusted_root = Path(cfg['coordinated_update']['review_root'])
    need(archive_path.is_absolute() and '..' not in archive_path.parts and
         archive_path != trusted_root and archive_path.is_relative_to(trusted_root),
         'archive_outside_trusted_review_root')
    need(any(asset.get('kind') == 'directory' and
             archive_path.is_relative_to(Path(asset.get('path', '')))
             for asset in cfg.get('recovery_policy', {}).get('required_assets', [])),
         'archive_not_recovery_declared')
    with release_verification_cache(), BoundDirectory(state_path) as state, ExitStack() as stack:
        # Determine policy root from native control parsing, without changing it.
        selected = binding._control(cfg)
        need(selected is not None, 'managed_update_required')
        policy_path = selected[2]
        policy = stack.enter_context(BoundDirectory(policy_path.parent))
        lock_paths = [state_path/'consumer-maintenance.lock', state_path/'writer.lock',
                      policy_path.parent/'writer.lock']
        held = []
        for path, directory in zip(lock_paths, [state, state, policy]):
            directory.read(path.name)  # Existing regular owned single-link locks only.
            stack.enter_context(locks.exclusive(path))
            held.append(locks.assert_owned(path))
        def guard():
            state.check(); policy.check()
            for path, handle, directory in zip(lock_paths, held, [state, state, policy]):
                need(locks.assert_owned(path) is handle, 'lock_handle_changed')
                info = os.stat(path.name, dir_fd=directory.fd, follow_symlinks=False)
                need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                     info.st_uid == os.getuid() and not info.st_mode & 0o022 and
                     (info.st_dev, info.st_ino) == (os.fstat(handle.fileno()).st_dev,
                                                   os.fstat(handle.fileno()).st_ino),
                     'lock_identity_changed')
        guard()
        archive = stack.enter_context(BoundDirectory(archive_path))
        archive_stat = os.fstat(archive.fd)
        need(stat.S_IMODE(archive_stat.st_mode) == 0o700 and
             archive_stat.st_dev == os.fstat(state.fd).st_dev, 'private_same_volume_archive_required')
        try:
            raw, source_identity = state.read(JOURNAL)
        except FileNotFoundError:
            # No recreation, no native call (it requires the source), no success
            # claim about the current tuple. Sync closes a prior unlink crash.
            archived, _ = archive.read(archive_name)
            parse_completed(archived, expected_sha256, expected_side)
            guard(); archive.check(); os.fsync(archive.fd); os.fsync(state.fd)
            return dict(status='already_absent', archive_only=True,
                        current_tuple_verified=False, publication_authorized=False,
                        journal_sha256=expected_sha256)
        journal = parse_completed(raw, expected_sha256, expected_side)
        def unchanged():
            guard()
            need(state.read(JOURNAL) == (raw, source_identity), 'journal_changed')
        unchanged()
        result = update.recover(cfg)
        need(result.get('read_only') is True and result.get('status') == 'complete' and
             result.get('verified_side') == expected_side, 'native_verified_outcome_mismatch')
        fault('verification:after_native')
        unchanged()
        def archive_guard():
            unchanged(); archive.check()
        create_archive(archive, archive_name, raw, fault, archive_guard)
        fault('retirement:before_unlink')
        unchanged()
        # Re-run the native read-only verifier after archive interruptions or
        # externally introduced tuple changes; keep all native locks held.
        need(update.recover(cfg) == result, 'native_result_changed')
        need(archive.read(archive_name)[0] == raw, 'archive_mismatch')
        fd = os.open(archive_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=archive.fd)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(archive.fd)
        need(archive.read(archive_name)[0] == raw, 'archive_mismatch')
        archive_guard()
        os.unlink(JOURNAL, dir_fd=state.fd)
        fault('retirement:after_unlink')
        guard(); archive.check(); os.fsync(state.fd)
        fault('retirement:after_directory_sync')
        return dict(status='retired', verified_side=expected_side,
                    current_tuple_verified=True, publication_authorized=False,
                    journal_sha256=expected_sha256, archive_path=str(archive_path/archive_name))



def retire_if_complete(cfg):
    """Retire a complete hinted journal; never recover or create history.

    The bounded hint is not authority. ``retire_completed`` verifies exact bytes
    and the native tuple under locks. A changed/absent source is not fresh proof.
    """
    path = Path(cfg['state_dir']) / JOURNAL
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES,
             'journal_hint_unavailable_use_native_recovery')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        need(len(raw) <= MAX_BYTES, 'journal_hint_unavailable_use_native_recovery')
    finally:
        os.close(fd)
    value = json.loads(raw)
    need(isinstance(value, dict) and value.get('status') == 'complete',
         'journal_requires_native_recovery')
    side = value.get('recovered_to', 'target')
    need(side in ('old', 'target'), 'unknown_completed_journal_outcome')
    digest = hashlib.sha256(raw).hexdigest()
    root = cfg.get('coordinated_update', {}).get('review_root')
    need(isinstance(root, str) and bool(root), 'managed_review_root_required')
    receipt = retire_completed(cfg, expected_sha256=digest, expected_side=side,
                               archive_directory=Path(root) / HISTORY)
    need(receipt.get('status') == 'retired' and
         receipt.get('current_tuple_verified') is True and
         receipt.get('verified_side') == side and
         receipt.get('journal_sha256') == digest and
         receipt.get('publication_authorized') is False,
         'fresh_completed_tuple_verification_required')
    return receipt
