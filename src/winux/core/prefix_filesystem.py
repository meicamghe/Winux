"""No-follow inventory of a managed Wine prefix for backup preparation.

This module never reads through a symlink and never copies file contents.
A future streaming writer must reopen each entry relative to a pinned
directory descriptor and re-check its inode and metadata before reading.
"""

import os
import stat
import unicodedata
from pathlib import Path


MAX_FILES = 250_000
MAX_DIRECTORIES = 100_000
MAX_FILE_BYTES = 20 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_COMPONENT_BYTES = 255

_COM_LINKS = {
    f"com{number}": f"/dev/ttyS{number - 1}"
    for number in range(1, 33)
}
_ALLOWED_DRIVE_LINKS = {"c:", "z:", *_COM_LINKS}


class PrefixScanError(ValueError):
    """The prefix contains an unsafe or unsupported filesystem object."""


def _open_absolute_directory(path):
    """Open every path component with O_NOFOLLOW, pinning the final root."""
    absolute = os.path.abspath(os.fspath(path))
    if not os.path.isabs(absolute):
        raise PrefixScanError("Prefix path must be absolute")

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.path.sep, flags)
    try:
        for component in Path(absolute).parts[1:]:
            if component in ("", ".", ".."):
                raise PrefixScanError("Invalid prefix path component")
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise PrefixScanError("Prefix root is not a directory")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _validate_member_path(value):
    if not isinstance(value, str) or not value or "\\x00" in value:
        raise PrefixScanError("Invalid archive path")
    if value.startswith("/") or chr(92) in value:
        raise PrefixScanError("Absolute and backslash paths are forbidden")
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) > MAX_PATH_BYTES:
        raise PrefixScanError("Archive path is too long")
    parts = value.split("/")
    if parts and len(parts[0]) >= 2 and parts[0][0].isalpha() and parts[0][1] == ":":
        raise PrefixScanError("Windows drive-prefixed paths are forbidden")
    if any(part in ("", ".", "..") for part in parts):
        raise PrefixScanError("Archive path contains an unsafe component")
    for part in parts:
        if len(part.encode("utf-8")) > MAX_COMPONENT_BYTES:
            raise PrefixScanError("Archive path component is too long")
    return unicodedata.normalize("NFC", value)


def _mount_id(descriptor):
    """Return the Linux mount ID for an open object, failing closed if absent."""
    try:
        with open(f"/proc/self/fdinfo/{descriptor}", encoding="ascii") as info:
            for line in info:
                if line.startswith("mnt_id:"):
                    return int(line.split(":", 1)[1].strip())
    except (OSError, ValueError):
        pass
    raise PrefixScanError("Cannot verify filesystem mount boundary")


def _same_object(before, after):
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and stat.S_IFMT(before.st_mode) == stat.S_IFMT(after.st_mode)
    )


def _scan_drive_links(directory_fd):
    initial = os.fstat(directory_fd)
    names = sorted(os.listdir(directory_fd))
    links = {}
    for name in names:
        _validate_member_path(f"dosdevices/{name}")
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISLNK(info.st_mode):
            raise PrefixScanError(
                f"Unexpected non-symlink in dosdevices: {name}"
            )
        if name not in _ALLOWED_DRIVE_LINKS:
            raise PrefixScanError(f"Unknown Wine drive mapping: {name}")
        target = os.readlink(name, dir_fd=directory_fd)
        expected = (
            "../drive_c" if name == "c:"
            else "/" if name == "z:"
            else _COM_LINKS[name]
        )
        if target != expected:
            raise PrefixScanError(
                f"Unexpected target for Wine drive mapping {name}"
            )
        links[name] = target

    final = os.fstat(directory_fd)
    if (initial.st_mtime_ns, initial.st_ctime_ns) != (final.st_mtime_ns, final.st_ctime_ns):
        raise PrefixScanError("dosdevices changed during scan")

    if links.get("c:") != "../drive_c":
        raise PrefixScanError("Wine dosdevices/c: mapping is missing")
    present_com = set(links).intersection(_COM_LINKS)
    if present_com:
        # Wine builds differ: observed defaults include COM1-COM4 and
        # COM1-COM32. Accept only a contiguous prefix beginning at COM1;
        # gaps, reordered aliases, and unexpected targets remain rejected.
        numbers = sorted(int(name[3:]) for name in present_com)
        if numbers != list(range(1, numbers[-1] + 1)):
            raise PrefixScanError("Non-contiguous Wine COM mapping set")
    return {
        "c": "drive_c",
        "z": "/" if "z:" in links else None,
        "serial": "wine-default" if present_com else None,
    }


def scan_prefix_tree(prefix_path):
    """Validate and inventory a prefix without following any symlink.

    Returns a deterministic inventory and logical Wine drive mappings.
    Symlink targets are inspected only in dosdevices and are never resolved.
    """
    root_fd = _open_absolute_directory(prefix_path)
    try:
        root_info = os.fstat(root_fd)
        if root_info.st_mode & (stat.S_ISUID | stat.S_ISGID):
            raise PrefixScanError("Setuid/setgid prefix root is forbidden")
        root_device = root_info.st_dev
        root_mount = _mount_id(root_fd)

        drive_info = os.stat("drive_c", dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISDIR(drive_info.st_mode):
            raise PrefixScanError("drive_c must be a real directory")

        inventory = []
        seen = set()
        file_count = 0
        directory_count = 0
        total_bytes = 0
        drive_mappings = None

        def add_record(relative, kind, info):
            normalized = _validate_member_path(relative)
            if normalized in seen:
                raise PrefixScanError("Duplicate normalized archive path")
            seen.add(normalized)
            inventory.append({
                "path": normalized,
                "type": kind,
                "mode": stat.S_IMODE(info.st_mode) & 0o755,
                "size": info.st_size if kind == "file" else 0,
                "mtime_ns": getattr(info, "st_mtime_ns", 0),
                "ctime_ns": getattr(info, "st_ctime_ns", 0),
                "nlink": info.st_nlink,
                "device": info.st_dev,
                "inode": info.st_ino,
            })

        def walk_directory(directory_fd, relative):
            nonlocal file_count, directory_count, total_bytes, drive_mappings
            directory_info = os.fstat(directory_fd)
            if directory_info.st_dev != root_device or _mount_id(directory_fd) != root_mount:
                raise PrefixScanError("Mounted filesystem inside prefix")
            if relative:
                add_record(relative, "directory", directory_info)
                directory_count += 1
                if directory_count > MAX_DIRECTORIES:
                    raise PrefixScanError("Prefix directory limit exceeded")

            names = sorted(os.listdir(directory_fd))
            for name in names:
                if not isinstance(name, str) or name in ("", ".", ".."):
                    raise PrefixScanError("Invalid filesystem entry name")
                child_relative = f"{relative}/{name}" if relative else name
                if relative == "" and name == ".winux-prefix.json":
                    metadata = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise PrefixScanError("Unsafe Winux metadata file")
                    continue

                if relative == "" and name == "dosdevices":
                    info = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                    if not stat.S_ISDIR(info.st_mode):
                        raise PrefixScanError("dosdevices must be a real directory")
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_fd,
                    )
                    try:
                        opened = os.fstat(child_fd)
                        if not _same_object(info, opened):
                            raise PrefixScanError("dosdevices changed during scan")
                        if _mount_id(child_fd) != root_mount:
                            raise PrefixScanError("Mounted filesystem inside prefix")
                        drive_mappings = _scan_drive_links(child_fd)
                        add_record(child_relative, "directory", opened)
                        directory_count += 1
                        if directory_count > MAX_DIRECTORIES:
                            raise PrefixScanError("Prefix directory limit exceeded")
                    finally:
                        os.close(child_fd)
                    continue

                before = os.stat(
                    name, dir_fd=directory_fd, follow_symlinks=False
                )
                if before.st_dev != root_device:
                    raise PrefixScanError("Mounted filesystem inside prefix")
                if before.st_mode & (stat.S_ISUID | stat.S_ISGID):
                    raise PrefixScanError(
                        f"Setuid/setgid filesystem object: {child_relative}"
                    )

                if stat.S_ISLNK(before.st_mode):
                    raise PrefixScanError(
                        f"Unexpected symlink in prefix: {child_relative}"
                    )
                if stat.S_ISDIR(before.st_mode):
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_fd,
                    )
                    try:
                        opened = os.fstat(child_fd)
                        if not _same_object(before, opened):
                            raise PrefixScanError(
                                f"Directory changed during scan: {child_relative}"
                            )
                        if _mount_id(child_fd) != root_mount:
                            raise PrefixScanError("Mounted filesystem inside prefix")
                        walk_directory(child_fd, child_relative)
                    finally:
                        os.close(child_fd)
                    continue

                if not stat.S_ISREG(before.st_mode):
                    raise PrefixScanError(
                        f"Special filesystem object: {child_relative}"
                    )
                if before.st_nlink != 1:
                    raise PrefixScanError(
                        f"Hard-linked file is unsupported: {child_relative}"
                    )
                if before.st_size < 0 or before.st_size > MAX_FILE_BYTES:
                    raise PrefixScanError(
                        f"File size limit exceeded: {child_relative}"
                    )
                file_count += 1
                total_bytes += before.st_size
                if file_count > MAX_FILES or total_bytes > MAX_TOTAL_BYTES:
                    raise PrefixScanError("Prefix file/size limit exceeded")

                file_fd = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                    dir_fd=directory_fd,
                )
                try:
                    opened = os.fstat(file_fd)
                    if not _same_object(before, opened):
                        raise PrefixScanError(
                            f"File changed during scan: {child_relative}"
                        )
                    if _mount_id(file_fd) != root_mount:
                        raise PrefixScanError("Mounted filesystem inside prefix")
                    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                        raise PrefixScanError(
                            f"Unsafe file object: {child_relative}"
                        )
                    after = os.fstat(file_fd)
                    if (
                        after.st_size != opened.st_size
                        or after.st_mtime_ns != opened.st_mtime_ns
                        or after.st_ctime_ns != opened.st_ctime_ns
                    ):
                        raise PrefixScanError(
                            f"File changed during scan: {child_relative}"
                        )
                    add_record(child_relative, "file", opened)
                finally:
                    os.close(file_fd)

            final_directory_info = os.fstat(directory_fd)
            if (directory_info.st_mtime_ns, directory_info.st_ctime_ns) != (
                final_directory_info.st_mtime_ns,
                final_directory_info.st_ctime_ns,
            ):
                raise PrefixScanError(f"Directory changed during scan: {relative or '.'}")

        walk_directory(root_fd, "")
        if drive_mappings is None:
            raise PrefixScanError("Wine dosdevices directory is missing")
        inventory.sort(key=lambda item: item["path"])
        return {
            "files": file_count,
            "directories": directory_count,
            "total_bytes": total_bytes,
            "drive_mappings": drive_mappings,
            "entries": inventory,
        }
    finally:
        os.close(root_fd)
