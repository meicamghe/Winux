import os
import tempfile
import unittest
from pathlib import Path

from winux.core.prefix_filesystem import (
    PrefixScanError,
    scan_prefix_tree,
)


class PrefixFilesystemScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "prefix"
        self.root.mkdir()
        (self.root / "drive_c").mkdir()
        (self.root / "drive_c" / "Program Files").mkdir()
        (self.root / "drive_c" / "Program Files" / "sample.txt").write_text(
            "safe payload", encoding="utf-8"
        )
        (self.root / "system.reg").write_text("WINE REGISTRY", encoding="utf-8")
        dos = self.root / "dosdevices"
        dos.mkdir()
        (dos / "c:").symlink_to("../drive_c")
        (dos / "z:").symlink_to("/")
        for number in range(1, 33):
            (dos / f"com{number}").symlink_to(f"/dev/ttyS{number - 1}")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scans_real_prefix_and_records_drive_aliases_logically(self):
        result = scan_prefix_tree(self.root)
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["drive_mappings"], {
            "c": "drive_c", "z": "/", "serial": "wine-default"
        })
        paths = {entry["path"] for entry in result["entries"]}
        self.assertIn("drive_c/Program Files/sample.txt", paths)
        self.assertIn("dosdevices", paths)
        self.assertNotIn("dosdevices/z:", paths)
        self.assertEqual(result["total_bytes"], len("safe payload") + len("WINE REGISTRY"))

    def test_does_not_follow_z_drive_host_root_link(self):
        sentinel = self.root.parent / "outside-sentinel"
        sentinel.write_text("host-private", encoding="utf-8")
        result = scan_prefix_tree(self.root)
        self.assertNotIn(str(sentinel), repr(result))
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "host-private")

    def test_rejects_unknown_symlink_outside_dosdevices(self):
        (self.root / "drive_c" / "escape").symlink_to(self.root.parent)
        with self.assertRaisesRegex(PrefixScanError, "Unexpected symlink"):
            scan_prefix_tree(self.root)

    def test_rejects_partial_com_mapping(self):
        (self.root / "dosdevices" / "com32").unlink()
        with self.assertRaisesRegex(PrefixScanError, "Partial Wine COM"):
            scan_prefix_tree(self.root)

    def test_rejects_wrong_c_drive_target(self):
        (self.root / "dosdevices" / "c:").unlink()
        (self.root / "dosdevices" / "c:").symlink_to(self.root / "drive_c")
        with self.assertRaisesRegex(PrefixScanError, "Unexpected target"):
            scan_prefix_tree(self.root)

    def test_rejects_symlinked_dosdevices_directory(self):
        dos = self.root / "dosdevices"
        dos.rename(self.root / "dosdevices-real")
        dos.symlink_to(self.root / "dosdevices-real", target_is_directory=True)
        with self.assertRaisesRegex(PrefixScanError, "dosdevices must be a real"):
            scan_prefix_tree(self.root)

    def test_rejects_hardlinked_regular_files(self):
        os.link(self.root / "system.reg", self.root / "second.reg")
        with self.assertRaisesRegex(PrefixScanError, "Hard-linked"):
            scan_prefix_tree(self.root)

    def test_rejects_special_files(self):
        os.mkfifo(self.root / "named-pipe")
        with self.assertRaisesRegex(PrefixScanError, "Special filesystem"):
            scan_prefix_tree(self.root)

    def test_rejects_symlinked_prefix_root(self):
        link = self.root.parent / "prefix-link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            scan_prefix_tree(link)

    def test_rejects_backslash_path_component(self):
        (self.root / "drive_c" / "bad\\\\name.txt").write_text(
            "unsafe", encoding="utf-8"
        )
        with self.assertRaisesRegex(PrefixScanError, "backslash"):
            scan_prefix_tree(self.root)

    def test_rejects_unicode_normalization_collisions(self):
        (self.root / "drive_c" / "café.txt").write_text("one", encoding="utf-8")
        (self.root / "drive_c" / "cafe\u0301.txt").write_text("two", encoding="utf-8")
        with self.assertRaisesRegex(PrefixScanError, "Duplicate normalized"):
            scan_prefix_tree(self.root)


if __name__ == "__main__":
    unittest.main()
