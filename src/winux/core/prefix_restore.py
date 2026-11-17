"""Internal, no-follow restore path for validated Winux prefix backups.

No archive extraction helpers are used. Restore always creates a new prefix;
existing destinations are never replaced.
"""
import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path

from winux.core.prefix import PrefixManager
from winux.core.prefix_archive import (
    PrefixArchiveError,
    _octal,
    _tar_string,
    inspect_prefix_backup,
)
from winux.core.prefix_filesystem import scan_prefix_tree
from winux.core.prefix_lock import prefix_operation_lock


class PrefixRestoreError(RuntimeError):
    """Restore failed without publishing a partial destination."""


def _open_directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open("/", flags)
    try:
        for component in Path(os.path.abspath(path)).parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _read_exact(fd, size, digest):
    chunks = []
    remaining = size
    while remaining:
        data = os.read(fd, min(1024 * 1024, remaining))
        if not data:
            raise PrefixRestoreError("Archive payload was truncated during restore")
        digest.update(data)
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("Short write while restoring prefix")
        view = view[written:]


def _open_parent(root_fd, relative):
    parts = relative.split("/")
    parent = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
            os.close(parent)
            parent = child
        return parent, parts[-1]
    except Exception:
        os.close(parent)
        raise


def _remove_tree_at(parent_fd, name):
    """Remove only the named staging tree, never following links."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        root_fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        return
    try:
        for child_name in os.listdir(root_fd):
            info = os.stat(child_name, dir_fd=root_fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _remove_tree_at(root_fd, child_name)
            else:
                os.unlink(child_name, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _rename_noreplace(old_fd, old_name, new_fd, new_name):
    """Use Linux renameat2(RENAME_NOREPLACE); fail closed if unavailable."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise PrefixRestoreError("Atomic no-replace rename is unavailable on this system")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(old_fd, os.fsencode(old_name), new_fd, os.fsencode(new_name), 1)
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(new_name)
        raise OSError(error, os.strerror(error), new_name)


def _extract_payload(archive_fd, payload_size, root_fd, inspection):
    digest = hashlib.sha256()
    records = inspection["entries"]
    record_index = 0
    remaining = payload_size

    while remaining >= 1024:
        header = _read_exact(archive_fd, 512, digest)
        remaining -= 512
        if header == bytes(512):
            second = _read_exact(archive_fd, 512, digest)
            remaining -= 512
            if second != bytes(512):
                raise PrefixRestoreError("Invalid tar end marker")
            while remaining:
                chunk = _read_exact(archive_fd, min(1024 * 1024, remaining), digest)
                if any(chunk):
                    raise PrefixRestoreError("Non-zero data after tar end marker")
                remaining -= len(chunk)
            break

        if record_index >= len(records):
            raise PrefixRestoreError("Archive contains more entries than its inspected inventory")
        kind_flag = header[156:157]
        kind = "directory" if kind_flag == b"5" else "file" if kind_flag in (b"0", b"\0") else None
        if kind is None:
            raise PrefixRestoreError("Unsupported tar entry type during restore")
        name = _tar_string(header[:100])
        prefix = _tar_string(header[345:500])
        path = prefix + "/" + name if prefix else name
        if kind == "directory":
            if not path.endswith("/"):
                raise PrefixRestoreError("Non-canonical directory path")
            path = path[:-1]
        size = _octal(header[124:136], "size")
        record = records[record_index]
        if record["path"] != path or record["type"] != kind or record["size"] != size:
            raise PrefixRestoreError("Archive entry changed after inspection")
        record_index += 1

        parent_fd, leaf = _open_parent(root_fd, path)
        try:
            if kind == "directory":
                if size:
                    raise PrefixRestoreError("Directory entry has data")
                os.mkdir(leaf, 0o700, dir_fd=parent_fd)
            else:
                file_fd = os.open(
                    leaf,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
                try:
                    left = size
                    while left:
                        chunk = _read_exact(archive_fd, min(1024 * 1024, left), digest)
                        remaining -= len(chunk)
                        _write_all(file_fd, chunk)
                        left -= len(chunk)
                    safe_mode = (record["mode"] & 0o700) | 0o400
                    os.fchmod(file_fd, safe_mode)
                    os.fsync(file_fd)
                finally:
                    os.close(file_fd)
        finally:
            os.close(parent_fd)

        if kind == "directory":
            padding = 0
        else:
            padding = (-size) % 512
            if padding:
                pad = _read_exact(archive_fd, padding, digest)
                remaining -= padding
                if any(pad):
                    raise PrefixRestoreError("Non-zero tar padding")

    if record_index != len(records):
        raise PrefixRestoreError("Archive inventory was not fully restored")
    if remaining != 0:
        raise PrefixRestoreError("Unexpected bytes remain in tar payload")
    if digest.hexdigest() != inspection["payload_sha256"]:
        raise PrefixRestoreError("Archive payload digest changed during restore")

    _fsync_directories(root_fd)


def _fsync_directories(directory_fd):
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            continue
        child_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        try:
            _fsync_directories(child_fd)
            os.fchmod(child_fd, 0o700)
            os.fsync(child_fd)
        finally:
            os.close(child_fd)
    os.fsync(directory_fd)


def restore_prefix(archive_path, prefix_name, *, prefix_manager=None):
    """Restore a backup as a new managed prefix; never overwrite an existing prefix."""
    manager = prefix_manager or PrefixManager()
    manager.validate_name(prefix_name)
    manager._ensure_base_dir()
    runtime_name = manager.runtime_manager.get_default_name()
    runtime = manager.runtime_manager.get(runtime_name)
    if not runtime.is_available():
        raise PrefixRestoreError("The selected local runtime is unavailable")

    archive_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    archive_fd = os.open(archive_path, archive_flags)
    archive_before = os.fstat(archive_fd)
    if not stat.S_ISREG(archive_before.st_mode) or archive_before.st_nlink != 1:
        os.close(archive_fd)
        raise PrefixArchiveError("Backup must be a single-link regular file")

    base_fd = _open_directory(manager.base_dir)
    stage_name = None
    published = False
    try:
        with prefix_operation_lock(prefix_name, blocking=False):
            try:
                os.stat(prefix_name, dir_fd=base_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(manager.base_dir / prefix_name)

            inspection = inspect_prefix_backup(None, _fd=archive_fd)
            if inspection["architecture"] != "win64":
                raise PrefixRestoreError("Unsupported prefix architecture")
            payload_size = os.pread(archive_fd, 8, len(b"WINUXPFX\x01"))
            if len(payload_size) != 8:
                raise PrefixRestoreError("Backup payload length is missing")
            payload_size = int.from_bytes(payload_size, "big")
            os.lseek(archive_fd, len(b"WINUXPFX\x01") + 8, os.SEEK_SET)

            stage_name = ".restore-" + secrets.token_hex(16)
            os.mkdir(stage_name, 0o700, dir_fd=base_fd)
            stage_fd = os.open(
                stage_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=base_fd,
            )
            try:
                _extract_payload(archive_fd, payload_size, stage_fd, inspection)

                dos_fd = os.open(
                    "dosdevices",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=stage_fd,
                )
                try:
                    os.symlink("../drive_c", "c:", dir_fd=dos_fd)
                    os.fsync(dos_fd)
                finally:
                    os.close(dos_fd)

                metadata = {
                    "name": prefix_name,
                    "architecture": "win64",
                    "runtime": runtime_name,
                    "format_version": 1,
                }
                metadata_fd = os.open(
                    ".winux-prefix.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=stage_fd,
                )
                try:
                    encoded = (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode("utf-8")
                    _write_all(metadata_fd, encoded)
                    os.fsync(metadata_fd)
                finally:
                    os.close(metadata_fd)

                stage_path = manager.base_dir / stage_name
                if not runtime.validate_prefix(stage_path):
                    raise PrefixRestoreError("Restored prefix failed local runtime validation")
                scan_prefix_tree(stage_path)

                current = os.fstat(archive_fd)
                if (archive_before.st_dev, archive_before.st_ino, archive_before.st_size,
                    archive_before.st_mtime_ns, archive_before.st_ctime_ns) != (
                    current.st_dev, current.st_ino, current.st_size,
                    current.st_mtime_ns, current.st_ctime_ns
                ):
                    raise PrefixRestoreError("Backup file changed during restore")

                _fsync_directories(stage_fd)
                os.fsync(stage_fd)
                _rename_noreplace(base_fd, stage_name, base_fd, prefix_name)
                os.fsync(base_fd)
                published = True
            finally:
                os.close(stage_fd)

        result = manager.get_path(prefix_name)
        return {"path": str(result), "architecture": "win64", "runtime": runtime_name,
                "files": inspection["files"], "directories": inspection["directories"],
                "total_bytes": inspection["total_bytes"]}
    finally:
        os.close(archive_fd)
        if stage_name and not published:
            _remove_tree_at(base_fd, stage_name)
        os.close(base_fd)
