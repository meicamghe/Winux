"""Internal streaming writer for managed Wine prefix backups."""
import hashlib
import json
import os
import stat
import tarfile
import secrets
from pathlib import Path

from winux.core.prefix import PrefixManager
from winux.core.prefix_filesystem import MAX_TOTAL_BYTES, _open_absolute_directory, scan_prefix_tree
from winux.core.prefix_lock import prefix_operation_lock
from winux.core.wine_processes import inspect_prefix_processes

MAGIC = b"WINUXPFX\x01"
CHUNK = 1024 * 1024
MAX_MANIFEST = 16 * 1024 * 1024
MAX_ARCHIVE = 110 * 1024 * 1024 * 1024


class PrefixBackupError(RuntimeError):
    pass


def _open_directory(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open("/", flags)
    try:
        for part in Path(os.path.abspath(path)).parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_entry(root_fd, entry):
    parts = entry["path"].split("/")
    parent = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        is_dir = entry["type"] == "directory"
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        if is_dir:
            flags |= os.O_DIRECTORY
        fd = os.open(parts[-1], flags, dir_fd=parent)
        info = os.fstat(fd)
        valid_type = stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode)
        if not valid_type or info.st_dev != entry["device"] or info.st_ino != entry["inode"]:
            os.close(fd)
            raise PrefixBackupError("Prefix entry identity changed: " + entry["path"])
        if (stat.S_IMODE(info.st_mode) & 0o755) != entry["mode"] or info.st_nlink != entry.get("nlink", 1):
            os.close(fd)
            raise PrefixBackupError("Prefix entry metadata changed: " + entry["path"])
        if (
            info.st_mtime_ns != entry["mtime_ns"]
            or info.st_ctime_ns != entry["ctime_ns"]
        ):
            os.close(fd)
            raise PrefixBackupError("Prefix entry timestamps changed since scan: " + entry["path"])
        if not is_dir and (info.st_size != entry["size"] or info.st_nlink != 1):
            os.close(fd)
            raise PrefixBackupError("Prefix file changed since scan: " + entry["path"])
        return fd, info
    finally:
        os.close(parent)


def _unchanged(a, b):
    return (a.st_dev, a.st_ino, a.st_mode, a.st_nlink, a.st_size, a.st_mtime_ns, a.st_ctime_ns) == (
        b.st_dev, b.st_ino, b.st_mode, b.st_nlink, b.st_size, b.st_mtime_ns, b.st_ctime_ns
    )


class _Reader:
    def __init__(self, fd, digest, remaining):
        self.fd, self.digest, self.remaining = fd, digest, remaining

    def read(self, size=-1):
        size = CHUNK if size is None or size < 0 else min(size, CHUNK)
        data = os.read(self.fd, min(size, self.remaining))
        self.remaining -= len(data)
        self.digest.update(data)
        return data


def _write_payload(prefix, inventory, payload_fd):
    """Stream a prefix into an already-open temporary file pinned to its parent."""
    root_fd = _open_absolute_directory(prefix)
    digest = hashlib.sha256()
    read_total = 0
    try:
        os.ftruncate(payload_fd, 0)
        with os.fdopen(os.dup(payload_fd), "wb", buffering=0) as output:
            with tarfile.open(fileobj=output, mode="w|", format=tarfile.USTAR_FORMAT) as tar:
                for entry in inventory["entries"]:
                    if entry["path"] == "dosdevices":
                        info = tarfile.TarInfo("dosdevices")
                        info.type = tarfile.DIRTYPE
                        info.mode = entry["mode"]
                        tar.addfile(info)
                        continue
                    fd, before = _open_entry(root_fd, entry)
                    try:
                        info = tarfile.TarInfo(entry["path"])
                        info.mode = entry["mode"]
                        info.mtime = entry["mtime_ns"] / 1_000_000_000
                        if entry["type"] == "directory":
                            info.type = tarfile.DIRTYPE
                            tar.addfile(info)
                        else:
                            info.type = tarfile.REGTYPE
                            info.size = entry["size"]
                            tar.addfile(info, _Reader(fd, digest, entry["size"]))
                            after = os.fstat(fd)
                            if not _unchanged(before, after):
                                raise PrefixBackupError("File mutated while streaming: " + entry["path"])
                            read_total += entry["size"]
                            if read_total > MAX_TOTAL_BYTES:
                                raise PrefixBackupError("Backup byte limit exceeded")
                    finally:
                        os.close(fd)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(root_fd)
    if read_total != inventory["total_bytes"]:
        raise PrefixBackupError("Streamed byte count mismatch")
    size = os.fstat(payload_fd).st_size
    if size > MAX_ARCHIVE:
        raise PrefixBackupError("Archive size limit exceeded")
    # Authenticate the complete tar stream, including headers and padding.
    archive_digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(payload_fd, min(CHUNK, size - offset), offset)
        if not chunk:
            raise PrefixBackupError("Temporary payload was truncated")
        archive_digest.update(chunk)
        offset += len(chunk)
    return size, archive_digest.hexdigest()


def _create_temporary_at(parent_fd, prefix):
    """Create a private temporary regular file relative to a pinned directory fd."""
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(16)}.tmp"
        try:
            return name, os.open(name, flags, 0o600, dir_fd=parent_fd)
        except FileExistsError:
            continue
    raise PrefixBackupError("Unable to allocate a unique temporary backup file")


def _verify_parent_path(path, parent_fd):
    """Ensure the user-visible parent path still names the pinned directory."""
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise PrefixBackupError("Backup destination parent changed during operation") from error
    pinned = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(current.st_mode)
        or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino)
    ):
        raise PrefixBackupError("Backup destination parent changed during operation")


def backup_prefix(prefix_name, destination, *, confirm_all_wine_apps_closed=False, prefix_manager=None):
    """Create an internal backup using only files beneath a pinned destination directory."""
    if confirm_all_wine_apps_closed is not True:
        raise PrefixBackupError("Explicit offline confirmation is required")
    manager = prefix_manager or PrefixManager()
    manager.validate_name(prefix_name)
    prefix = manager.get_path(prefix_name)
    destination = Path(os.path.abspath(os.fspath(destination)))
    if not destination.name or destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if os.path.commonpath((str(prefix.resolve()), str(destination))) == str(prefix.resolve()):
        raise PrefixBackupError("Destination must be outside the source prefix")

    parent_fd = _open_directory(destination.parent)
    payload_name = archive_name = None
    payload_fd = archive_fd = -1
    try:
        _verify_parent_path(destination.parent, parent_fd)
        with prefix_operation_lock(prefix_name, blocking=False):
            state = inspect_prefix_processes(prefix)
            if state["state"] != "clear":
                raise PrefixBackupError("Wine process state is " + state["state"] + "; refusing backup")
            inventory = scan_prefix_tree(prefix)
            metadata = manager._read_metadata(prefix)
            if not manager.get_runtime(prefix_name).is_available():
                raise PrefixBackupError("Prefix runtime is unavailable")

            payload_name, payload_fd = _create_temporary_at(parent_fd, ".winux-payload-")
            payload_size, payload_hash = _write_payload(prefix, inventory, payload_fd)

            # Re-scan to detect tree/drive-map changes during the stream.
            if scan_prefix_tree(prefix) != inventory:
                raise PrefixBackupError("Prefix tree changed during backup")
            manifest = {
                "format": "winux-prefix-backup", "format_version": 1,
                "architecture": metadata["architecture"], "runtime": metadata["runtime"],
                "files": inventory["files"], "directories": inventory["directories"],
                "total_bytes": inventory["total_bytes"], "drive_mappings": inventory["drive_mappings"],
                "payload": {"name": "payload.tar", "size": payload_size, "sha256": payload_hash},
                "entries": inventory["entries"],
            }
            encoded = json.dumps(
                manifest, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode()
            if len(encoded) > MAX_MANIFEST:
                raise PrefixBackupError("Manifest size limit exceeded")

            archive_name, archive_fd = _create_temporary_at(parent_fd, ".winux-backup-")
            with os.fdopen(archive_fd, "wb", buffering=0) as output:
                archive_fd = -1
                output.write(MAGIC)
                output.write(payload_size.to_bytes(8, "big"))
                copied = 0
                while copied < payload_size:
                    chunk = os.pread(payload_fd, min(CHUNK, payload_size - copied), copied)
                    if not chunk:
                        raise PrefixBackupError("Payload truncated during publication")
                    copied += len(chunk)
                    output.write(chunk)
                output.write(len(encoded).to_bytes(8, "big"))
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())

            _verify_parent_path(destination.parent, parent_fd)
            # linkat is atomic and fails if the destination name already exists.
            os.link(
                archive_name, destination.name,
                src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            try:
                _verify_parent_path(destination.parent, parent_fd)
            except Exception:
                os.unlink(destination.name, dir_fd=parent_fd)
                os.fsync(parent_fd)
                raise
            os.fsync(parent_fd)
            os.unlink(archive_name, dir_fd=parent_fd)
            archive_name = None
            return {
                "path": str(destination), "files": inventory["files"],
                "directories": inventory["directories"], "total_bytes": inventory["total_bytes"],
                "payload_sha256": payload_hash,
                "quiescence": "advisory-clear-plus-user-confirmation",
            }
    finally:
        for descriptor in (payload_fd, archive_fd):
            if descriptor >= 0:
                os.close(descriptor)
        for name in (payload_name, archive_name):
            if name:
                try:
                    os.unlink(name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
        os.close(parent_fd)
