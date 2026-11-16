import struct
import tempfile
import unittest
from pathlib import Path

from winux.core.shell_link import parse_shell_link_target, resolve_shell_link_target


CLSID = bytes.fromhex("0114020000000000C000000000000046")


def make_link(base, suffix=""):
    header = struct.pack("<I", 0x4C) + CLSID + struct.pack("<I", 0x2)
    header += bytes(0x4C - len(header))
    base_bytes = base.encode("cp1252") + bytes([0])
    suffix_bytes = suffix.encode("cp1252") + bytes([0])
    info_size = 0x1C + len(base_bytes) + len(suffix_bytes)
    info = struct.pack("<III", info_size, 0x1C, 0x1)
    info += struct.pack("<IIII", 0, 0x1C, 0, 0x1C + len(base_bytes))
    return header + info + base_bytes + suffix_bytes


def make_unicode_link(base, suffix=""):
    header = struct.pack("<I", 0x4C) + CLSID + struct.pack("<I", 0x2)
    header += bytes(0x4C - len(header))
    base_ansi = base.encode("cp1252", errors="replace") + bytes([0])
    suffix_ansi = suffix.encode("cp1252", errors="replace") + bytes([0])
    base_wide = base.encode("utf-16le") + bytes(2)
    suffix_wide = suffix.encode("utf-16le") + bytes(2)
    base_wide_offset = 0x24 + len(base_ansi) + len(suffix_ansi)
    suffix_wide_offset = base_wide_offset + len(base_wide)
    info_size = suffix_wide_offset + len(suffix_wide)
    info = struct.pack("<III", info_size, 0x24, 0x1)
    info += struct.pack(
        "<IIIIII",
        0,
        0x24,
        0,
        0x24 + len(base_ansi),
        base_wide_offset,
        suffix_wide_offset,
    )
    return header + info + base_ansi + suffix_ansi + base_wide + suffix_wide


class ShellLinkTests(unittest.TestCase):
    def test_parses_absolute_local_target_and_suffix(self):
        data = make_link(r"C:\Program Files\Example", "app.exe")
        self.assertEqual(
            parse_shell_link_target(data),
            r"C:\Program Files\Example\app.exe",
        )

    def test_rejects_invalid_or_unsupported_links(self):
        self.assertIsNone(parse_shell_link_target(b"short"))
        data = bytearray(make_link(r"C:\Example", "app.exe"))
        data[4] = 0
        self.assertIsNone(parse_shell_link_target(data))
        data = bytearray(make_link(r"C:\Example", "app.exe"))
        struct.pack_into("<I", data, 20, 0)
        self.assertIsNone(parse_shell_link_target(data))

    def test_parses_unicode_linkinfo_paths(self):
        data = make_unicode_link(r"C:\\Program Files\\例子", "应用.exe")
        self.assertEqual(
            parse_shell_link_target(data),
            r"C:\\Program Files\\例子\\应用.exe",
        )

    def test_rejects_linkinfo_offsets_outside_the_file(self):
        data = bytearray(make_link(r"C:\\Example", "app.exe"))
        struct.pack_into("<I", data, 0x4C + 16, 0xFFFFFFF0)
        self.assertIsNone(parse_shell_link_target(data))

    def test_resolves_only_existing_exe_inside_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            drive = root / "drive_c"
            app = drive / "Program Files" / "Example" / "app.exe"
            app.parent.mkdir(parents=True)
            app.write_bytes(b"MZ")
            data = make_link(r"C:\Program Files\Example", "app.exe")
            self.assertEqual(resolve_shell_link_target(data, root), app)
            missing = make_link(r"C:\Program Files\Example", "missing.exe")
            self.assertIsNone(resolve_shell_link_target(missing, root))
            outside = make_link(r"D:\Example", "app.exe")
            self.assertIsNone(resolve_shell_link_target(outside, root))


if __name__ == "__main__":
    unittest.main()
