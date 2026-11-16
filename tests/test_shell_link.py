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
    info += struct.pack("<III", 0x1C, 0, 0x1C + len(base_bytes))
    info += bytes(4)
    return header + info + base_bytes + suffix_bytes


class ShellLinkTests(unittest.TestCase):
    def test_parses_absolute_local_target_and_suffix(self):
        data = make_link(r"C:\\Program Files\\Example", "app.exe")
        self.assertEqual(
            parse_shell_link_target(data),
            r"C:\\Program Files\\Example\\app.exe",
        )

    def test_rejects_invalid_or_unsupported_links(self):
        self.assertIsNone(parse_shell_link_target(b"short"))
        data = bytearray(make_link(r"C:\\Example", "app.exe"))
        data[4] = 0
        self.assertIsNone(parse_shell_link_target(data))
        data = bytearray(make_link(r"C:\\Example", "app.exe"))
        struct.pack_into("<I", data, 20, 0)
        self.assertIsNone(parse_shell_link_target(data))

    def test_resolves_only_existing_exe_inside_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            drive = root / "drive_c"
            app = drive / "Program Files" / "Example" / "app.exe"
            app.parent.mkdir(parents=True)
            app.write_bytes(b"MZ")
            data = make_link(r"C:\\Program Files\\Example", "app.exe")
            self.assertEqual(resolve_shell_link_target(data, root), app)
            missing = make_link(r"C:\\Program Files\\Example", "missing.exe")
            self.assertIsNone(resolve_shell_link_target(missing, root))
            outside = make_link(r"D:\\Example", "app.exe")
            self.assertIsNone(resolve_shell_link_target(outside, root))


if __name__ == "__main__":
    unittest.main()
