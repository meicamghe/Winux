import tempfile
import unittest
from pathlib import Path

from winux.core.desktop import DesktopManager


def make_link(base, suffix=""):
    import struct
    clsid = bytes.fromhex("0114020000000000C000000000000046")
    header = struct.pack("<I", 0x4C) + clsid + struct.pack("<I", 0x2)
    header += bytes(0x4C - len(header))
    base_bytes = base.encode("cp1252") + b"\\x00"
    suffix_bytes = suffix.encode("cp1252") + b"\\x00"
    size = 0x1C + len(base_bytes) + len(suffix_bytes)
    info = struct.pack("<III", size, 0x1C, 0x1)
    info += struct.pack("<III", 0x1C, 0, 0x1C + len(base_bytes))
    info += bytes(4)
    return header + info + base_bytes + suffix_bytes


class StartMenuDiscoveryTests(unittest.TestCase):
    def test_discovers_only_existing_executables_inside_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            drive = prefix / "drive_c"
            menu = drive / "ProgramData/Microsoft/Windows/Start Menu/Programs"
            menu.mkdir(parents=True)
            executable = drive / "Program Files/Example/app.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"MZ")
            (menu / "Example.lnk").write_bytes(
                make_link(r"C:\\Program Files\\Example", "app.exe")
            )
            (menu / "Missing.lnk").write_bytes(
                make_link(r"C:\\Program Files\\Example", "missing.exe")
            )
            manager = object.__new__(DesktopManager)
            result = manager.discover_start_menu_shortcuts(prefix)
            self.assertEqual([item["name"] for item in result["shortcuts"]], ["Example"])
            self.assertEqual(result["shortcuts"][0]["executable_path"], str(executable))
            self.assertEqual(result["errors"], [])

    def test_ignores_symlinked_shortcut(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            drive = prefix / "drive_c"
            menu = drive / "ProgramData/Microsoft/Windows/Start Menu/Programs"
            menu.mkdir(parents=True)
            target = root / "external.lnk"
            target.write_bytes(make_link(r"C:\\Example", "app.exe"))
            (menu / "linked.lnk").symlink_to(target)
            manager = object.__new__(DesktopManager)
            result = manager.discover_start_menu_shortcuts(prefix)
            self.assertEqual(result["shortcuts"], [])


if __name__ == "__main__":
    unittest.main()
