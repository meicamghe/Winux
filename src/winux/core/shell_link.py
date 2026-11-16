"""Conservative parser for Windows Shell Link (.lnk) target paths.

Only absolute local targets represented by LinkInfo are accepted. Relative,
network, IDList-only, malformed, and out-of-prefix targets are intentionally
not guessed.
"""
import struct
from pathlib import Path, PureWindowsPath


_HEADER_SIZE = 0x4C
_LINK_CLSID = bytes.fromhex("0114020000000000C000000000000046")


def _read_c_string(data, offset, unicode_offset=0):
    if not offset:
        return None
    start = unicode_offset or offset
    if start < 0 or start >= len(data):
        return None
    if unicode_offset:
        end = start
        while end + 1 < len(data) and data[end:end + 2] != bytes([0, 0]):
            end += 2
        raw = data[start:end]
        try:
            return raw.decode("utf-16le")
        except UnicodeDecodeError:
            return None
    end = data.find(bytes([0]), start)
    if end < 0:
        return None
    return data[start:end].decode("cp1252", errors="replace")


def parse_shell_link_target(data):
    """Return the absolute local Windows target from a valid .lnk byte stream."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < _HEADER_SIZE:
        return None
    data = bytes(data)
    if struct.unpack_from("<I", data, 0)[0] != _HEADER_SIZE:
        return None
    if data[4:20] != _LINK_CLSID:
        return None

    flags = struct.unpack_from("<I", data, 20)[0]
    if not flags & 0x2:  # HasLinkInfo
        return None
    link_info_offset = _HEADER_SIZE
    if len(data) < link_info_offset + 0x1C:
        return None

    size, header_size, info_flags = struct.unpack_from(
        "<III", data, link_info_offset
    )
    if size < 0x1C or link_info_offset + size > len(data):
        return None
    if header_size < 0x1C or header_size > size:
        return None
    if not info_flags & 0x1:  # VolumeIDAndLocalBasePath
        return None

    base_offset = struct.unpack_from("<I", data, link_info_offset + 16)[0]
    suffix_offset = struct.unpack_from("<I", data, link_info_offset + 24)[0]
    base_unicode = suffix_unicode = 0
    if header_size >= 0x24:
        base_unicode, suffix_unicode = struct.unpack_from(
            "<II", data, link_info_offset + 28
        )

    def valid_offset(offset):
        return not offset or header_size <= offset < size

    if (
        not base_offset
        or not valid_offset(base_offset)
        or not valid_offset(suffix_offset)
        or not valid_offset(base_unicode)
        or not valid_offset(suffix_unicode)
    ):
        return None

    region = data[link_info_offset:link_info_offset + size]
    base = _read_c_string(region, base_offset, base_unicode)
    suffix = _read_c_string(region, suffix_offset, suffix_unicode)
    if not base:
        return None

    candidate = PureWindowsPath(base)
    if not candidate.is_absolute() or candidate.drive.startswith("\\\\"):
        return None
    if suffix:
        candidate = candidate / suffix
    return str(candidate)


def resolve_shell_link_target(data, prefix_path):
    """Resolve a parsed C: target only when it exists inside prefix drive_c."""
    target = parse_shell_link_target(data)
    if not target:
        return None
    windows_path = PureWindowsPath(target)
    if windows_path.drive.upper() != "C:" or not windows_path.is_absolute():
        return None

    drive_c = Path(prefix_path) / "drive_c"
    if drive_c.is_symlink() or not drive_c.is_dir():
        return None
    path = drive_c.joinpath(*windows_path.parts[1:])
    try:
        root = drive_c.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if resolved.suffix.casefold() != ".exe" or not resolved.is_file():
        return None
    return resolved
