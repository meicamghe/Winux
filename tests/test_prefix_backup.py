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


if __name__ == "__main__":
    unittest.main()
