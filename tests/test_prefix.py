import json
import logging
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winux.core.prefix import PrefixManager


class PrefixManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.logger = logging.getLogger("winux.prefix")
        self.original_handlers = self.logger.handlers[:]
        for handler in self.original_handlers:
            self.logger.removeHandler(handler)
        self.home_patcher = patch.object(Path, "home", return_value=self.home)
        self.home_patcher.start()
        self.manager = PrefixManager()

    def tearDown(self):
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()
        for handler in self.original_handlers:
            self.logger.addHandler(handler)
        self.home_patcher.stop()
        self.temp_dir.cleanup()

    def make_prefix(self, name="test-prefix", architecture=None):
        path = self.manager.base_dir / name
        path.mkdir()
        (path / "system.reg").write_text("WINE REGISTRY\n", encoding="utf-8")
        if architecture:
            (path / ".winux-prefix.json").write_text(
                json.dumps({"name": name, "architecture": architecture}),
                encoding="utf-8",
            )
        return path

    def test_validate_name_rejects_unsafe_names(self):
        for name in ("", "../escape", "two words", "name/child", "a" * 65):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.manager.validate_name(name)

    def test_validate_name_accepts_supported_characters(self):
        self.manager.validate_name("app_01-Test")

    def test_normalize_x64_architecture(self):
        self.assertEqual(self.manager.normalize_architecture("x64"), "win64")
        self.assertEqual(self.manager.normalize_architecture("win64"), "win64")

    def test_create_initializes_wine64_prefix_and_metadata(self):
        def initialize(command, env, **kwargs):
            prefix = Path(env["WINEPREFIX"])
            (prefix / "system.reg").write_text("WINE REGISTRY\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("winux.core.prefix.shutil.which", return_value="/usr/bin/wineboot"), patch(
            "winux.core.prefix.subprocess.run", side_effect=initialize
        ) as run:
            path = self.manager.create("fresh-prefix", architecture="x64")

        self.assertTrue((path / "system.reg").is_file())
        metadata = json.loads((path / ".winux-prefix.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["architecture"], "win64")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/wineboot", "--init"])
        self.assertEqual(run.call_args.kwargs["env"]["WINEARCH"], "win64")

    def test_create_removes_partial_prefix_after_failure(self):
        def fail_initialization(command, env, **kwargs):
            (Path(env["WINEPREFIX"]) / "partial").touch()
            return subprocess.CompletedProcess(command, 1, "", "wineboot failed")

        with patch("winux.core.prefix.shutil.which", return_value="/usr/bin/wineboot"), patch(
            "winux.core.prefix.subprocess.run", side_effect=fail_initialization
        ):
            with self.assertRaisesRegex(RuntimeError, "wineboot failed"):
                self.manager.create("broken-prefix")

        self.assertFalse((self.manager.base_dir / "broken-prefix").exists())

    def test_list_ignores_invalid_and_symlink_entries(self):
        self.make_prefix("valid")
        invalid = self.manager.base_dir / "invalid"
        invalid.mkdir()
        (self.manager.base_dir / "link").symlink_to(
            self.manager.base_dir / "valid", target_is_directory=True
        )

        self.assertEqual(self.manager.list(), ["valid"])

    def test_get_architecture_reads_metadata_and_supports_legacy_prefixes(self):
        self.make_prefix("modern", "win64")
        self.make_prefix("legacy")

        self.assertEqual(self.manager.get_architecture("modern"), "win64")
        self.assertEqual(self.manager.get_architecture("legacy"), "win64")

    def test_delete_requires_explicit_confirmation(self):
        self.make_prefix("to-delete")

        with self.assertRaises(PermissionError):
            self.manager.delete("to-delete")

        self.assertTrue((self.manager.base_dir / "to-delete").exists())
        self.assertTrue(self.manager.delete("to-delete", confirm=True))
        self.assertFalse((self.manager.base_dir / "to-delete").exists())


if __name__ == "__main__":
    unittest.main()
