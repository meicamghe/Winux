import os
import tempfile
import unittest
from pathlib import Path
from winux.core.prefix_backup import PrefixBackupError, _open_entry, _unchanged
from winux.core.prefix_filesystem import _open_absolute_directory


class BackupWriterPrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "prefix"
        (self.root / "drive_c").mkdir(parents=True)
        (self.root / "dosdevices").mkdir()
        (self.root / "dosdevices" / "c:").symlink_to("../drive_c")
        self.file = self.root / "drive_c" / "sample"
        self.file.write_bytes(b"hello")

    def _entry(self):
        st = self.file.stat()
        return {"path":"drive_c/sample","type":"file","device":st.st_dev,"inode":st.st_ino,
                "mode":st.st_mode & 0o755,"nlink":st.st_nlink,"size":st.st_size,
                "mtime_ns":st.st_mtime_ns,"ctime_ns":st.st_ctime_ns}

    def test_open_is_descriptor_relative_and_validates_identity(self):
        root = _open_absolute_directory(self.root)
        try:
            fd, before = _open_entry(root, self._entry())
            try:
                self.assertEqual(os.read(fd, 5), b"hello")
                self.assertTrue(_unchanged(before, os.fstat(fd)))
            finally:
                os.close(fd)
        finally:
            os.close(root)

    def test_replacement_is_rejected(self):
        entry = self._entry()
        replacement = self.file.with_suffix(".new")
        replacement.write_bytes(b"hello")
        os.replace(replacement, self.file)
        root = _open_absolute_directory(self.root)
        try:
            with self.assertRaises(PrefixBackupError):
                _open_entry(root, entry)
        finally:
            os.close(root)

    def test_writer_output_passes_strict_inspector(self):
        from unittest.mock import patch
        from winux.core.prefix_backup import backup_prefix
        from winux.core.prefix_archive import inspect_prefix_backup
        class Runtime:
            def is_available(self): return True
        class Manager:
            def validate_name(self, name): self.asserted_name = name
            def get_path(self, name): return self.root
            def _read_metadata(self, path): return {"architecture":"win64","runtime":"test-runtime"}
            def get_runtime(self, name): return Runtime()
        manager=Manager(); manager.root=self.root
        (self.root / "drive_c" / "nested").mkdir()
        (self.root / "drive_c" / "nested" / "document.bin").write_bytes(b"prefix-data")
        destination=Path(self.temp.name)/"roundtrip.wux"
        with patch("winux.core.prefix_backup.inspect_prefix_processes", return_value={"state":"clear"}):
            backup_prefix("test-prefix",destination,confirm_all_wine_apps_closed=True,prefix_manager=manager)
        result=inspect_prefix_backup(destination)
        self.assertEqual(result["files"],2)
        self.assertEqual(result["total_bytes"],16)
        self.assertEqual(result["architecture"],"win64")

if __name__ == "__main__":
    unittest.main()

    def test_destination_parent_symlink_swap_is_rejected_before_temp_creation(self):
        from unittest.mock import patch
        import winux.core.prefix_backup as backup_module

        destination_parent = Path(self.temp.name) / "destination"
        destination_parent.mkdir()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("outside data")
        moved_parent = destination_parent.with_name("destination-pinned")
        original_open = backup_module._open_directory

        class Runtime:
            def is_available(self):
                return True

        class Manager:
            def validate_name(self, name):
                self.asserted_name = name
            def get_path(self, name):
                return self.root
            def _read_metadata(self, path):
                return {"architecture": "win64", "runtime": "test-runtime"}
            def get_runtime(self, name):
                return Runtime()

        manager = Manager()
        manager.root = self.root

        def swap_parent_after_open(path):
            descriptor = original_open(path)
            if Path(path) == destination_parent:
                destination_parent.rename(moved_parent)
                destination_parent.symlink_to(outside, target_is_directory=True)
            return descriptor

        with (
            patch("winux.core.prefix_backup._open_directory", side_effect=swap_parent_after_open),
            patch("winux.core.prefix_backup.inspect_prefix_processes", return_value={"state": "clear"}),
        ):
            with self.assertRaisesRegex(PrefixBackupError, "parent changed"):
                backup_module.backup_prefix(
                    "test-prefix",
                    destination_parent / "backup.wux",
                    confirm_all_wine_apps_closed=True,
                    prefix_manager=manager,
                )

        self.assertTrue(destination_parent.is_symlink())
        self.assertEqual(sentinel.read_text(), "outside data")
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(list(moved_parent.iterdir()), [])
