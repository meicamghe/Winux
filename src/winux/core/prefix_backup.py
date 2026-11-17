"""Internal streaming writer for managed Wine prefix backups."""
import hashlib
import json
import os
import stat
import tarfile
import tempfile
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
        if not is_dir and (
            info.st_size != entry["size"] or info.st_mtime_ns != entry["mtime_ns"]
            or info.st_ctime_ns != entry["ctime_ns"] or info.st_nlink != 1
        ):
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


def _write_payload(prefix, inventory, payload_path):
    root_fd = _open_absolute_directory(prefix)
    digest = hashlib.sha256()
    read_total = 0
    try:
        with open(payload_path, "wb", buffering=0) as output:
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
    size = os.path.getsize(payload_path)
    if size > MAX_ARCHIVE:
        raise PrefixBackupError("Archive size limit exceeded")
    return size, digest.hexdigest()


def backup_prefix(prefix_name, destination, *, confirm_all_wine_apps_closed=False, prefix_manager=None):
    """Create an internal backup. Confirmation is not a race-free quiescence guarantee."""
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
    payload_path = archive_path = None
    try:
        with prefix_operation_lock(prefix_name, blocking=False):
            state = inspect_prefix_processes(prefix)
            if state["state"] != "clear":
                raise PrefixBackupError("Wine process state is " + state["state"] + "; refusing backup")
            inventory = scan_prefix_tree(prefix)
            metadata = manager._read_metadata(prefix)
            if not manager.get_runtime(prefix_name).is_available():
                raise PrefixBackupError("Prefix runtime is unavailable")
            fd, payload_path = tempfile.mkstemp(prefix=".winux-payload-", dir=destination.parent)
            os.close(fd)
            payload_size, payload_hash = _write_payload(prefix, inventory, payload_path)
            manifest = {
                "format": "winux-prefix-backup", "format_version": 1,
                "architecture": metadata["architecture"], "runtime": metadata["runtime"],
                "files": inventory["files"], "directories": inventory["directories"],
                "total_bytes": inventory["total_bytes"], "drive_mappings": inventory["drive_mappings"],
                "payload": {"name": "payload.tar", "size": payload_size, "sha256": payload_hash},
                "entries": inventory["entries"],
            }
            encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if len(encoded) > MAX_MANIFEST:
                raise PrefixBackupError("Manifest size limit exceeded")
            fd, archive_path = tempfile.mkstemp(prefix=".winux-backup-", dir=destination.parent)
            with os.fdopen(fd, "wb", buffering=0) as output:
                output.write(MAGIC)
                output.write(payload_size.to_bytes(8, "big"))
                with open(payload_path, "rb", buffering=0) as source:
                    copied = 0
                    while True:
                        chunk = source.read(CHUNK)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > payload_size:
                            raise PrefixBackupError("Payload changed during publication")
                        output.write(chunk)
                if copied != payload_size:
                    raise PrefixBackupError("Payload truncated during publication")
                output.write(len(encoded).to_bytes(8, "big"))
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.link(os.path.basename(archive_path), destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
            os.fsync(parent_fd)
            os.unlink(archive_path)
            archive_path = None
            return {"path": str(destination), "files": inventory["files"], "directories": inventory["directories"],
                    "total_bytes": inventory["total_bytes"], "payload_sha256": payload_hash,
                    "quiescence": "advisory-clear-plus-user-confirmation"}
    finally:
        os.close(parent_fd)
        for path in (payload_path, archive_path):
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
