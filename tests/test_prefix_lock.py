import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winux.core.prefix_lock import prefix_operation_lock


class PrefixOperationLockTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.home_patcher = patch.object(Path, "home", return_value=self.home)
        self.home_patcher.start()

    def tearDown(self):
        self.home_patcher.stop()
        self.temp_dir.cleanup()

    def test_lock_is_reentrant_only_after_release_and_contended_lock_fails_fast(self):
        with prefix_operation_lock("sample"):
            with self.assertRaisesRegex(RuntimeError, "Another operation"):
                with prefix_operation_lock("sample", blocking=False):
                    self.fail("contended lock must not be acquired")

        with prefix_operation_lock("sample", blocking=False):
            pass

    def test_lock_file_is_private_regular_file(self):
        with prefix_operation_lock("sample"):
            lock_file = self.home / ".local/share/winux/locks/sample.lock"
            self.assertTrue(lock_file.is_file())
            self.assertEqual(lock_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(lock_file.parent.stat().st_mode & 0o777, 0o700)

    def test_rejects_invalid_prefix_names(self):
        for name in ("", "../escape", "a/b", "a" * 65, None):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    with prefix_operation_lock(name):
                        pass

    def test_rejects_symlink_lock_file(self):
        target = self.home / "outside"
        target.write_text("preserve", encoding="utf-8")
        lock_dir = self.home / ".local/share/winux/locks"
        lock_dir.mkdir(parents=True)
        (lock_dir / "sample.lock").symlink_to(target)

        with self.assertRaises(OSError):
            with prefix_operation_lock("sample"):
                pass
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
