import json
import logging
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

        self.runtime = Mock()
        self.runtime.name = "test-runtime"
        self.runtime.is_available.return_value = True
        self.runtime.validate_prefix.side_effect = (
            lambda path: (
                path.is_dir()
                and not path.is_symlink()
                and (path / "system.reg").is_file()
                and not (path / "system.reg").is_symlink()
            )
        )

        self.runtime_manager = Mock()
        def get_runtime(name=None):
            if name in (None, "test-runtime"):
                return self.runtime
            raise ValueError(f"Unknown runtime: {name}")

        self.runtime_manager.get.side_effect = get_runtime
        self.runtime_manager.get_default_name.return_value = "test-runtime"

        self.manager = PrefixManager(runtime_manager=self.runtime_manager)

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

    def test_constructor_rejects_symlinked_prefix_log_file(self):
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()

        log_file = self.home / ".local/share/winux/logs/prefix-manager.log"
        log_file.unlink()
        target = self.home / "outside-prefix.log"
        target.write_text("private", encoding="utf-8")
        log_file.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "log file must not be a symbolic link"):
            PrefixManager(runtime_manager=self.runtime_manager)

        self.assertEqual(target.read_text(encoding="utf-8"), "private")

    def test_prefix_and_log_directories_are_private(self):
        self.assertEqual(self.manager.base_dir.stat().st_mode & 0o777, 0o700)
        log_dir = self.home / ".local/share/winux/logs"
        self.assertEqual(log_dir.stat().st_mode & 0o777, 0o700)
        log_file = log_dir / "prefix-manager.log"
        self.assertEqual(log_file.stat().st_mode & 0o777, 0o600)

    def test_constructor_rejects_symlinked_prefix_directory(self):
        root = self.home / ".local/share/winux"
        real = root / "real-prefixes"
        real.mkdir()
        linked = root / "prefixes"
        linked.rename(root / "prefixes-original")
        linked.symlink_to(real, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            PrefixManager(runtime_manager=self.runtime_manager)

    def test_constructor_rejects_symlinked_prefix_parent(self):
        local = self.home / ".local"
        real = self.home / "real-local"
        real.mkdir()
        linked = local
        linked.rename(self.home / "local-original")
        linked.symlink_to(real, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            PrefixManager(runtime_manager=self.runtime_manager)

    def test_prefix_root_is_revalidated_before_creation(self):
        root = self.manager.base_dir
        real = self.home / "real-prefixes"
        root.rename(real)
        root.symlink_to(real, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            self.manager.create("unsafe-root")

        self.runtime.create_prefix.assert_not_called()

    def test_prefix_root_is_revalidated_before_listing(self):
        root = self.manager.base_dir
        real = self.home / "real-prefixes"
        root.rename(real)
        root.symlink_to(real, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            self.manager.list()

    def test_validate_name_rejects_unsafe_names(self):
        for name in ("", "../escape", "two words", "name/child", "a" * 65):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.manager.validate_name(name)

    def test_validate_name_accepts_supported_characters(self):
        self.manager.validate_name("app_01-Test")

    def test_normalize_x86_and_x64_to_win64(self):
        for architecture in ("x86", "x64", "win64"):
            with self.subTest(architecture=architecture):
                self.assertEqual(
                    self.manager.normalize_architecture(architecture),
                    "win64",
                )

    def test_normalize_rejects_non_string_architecture(self):
        for architecture in (None, [], {}, True, 64):
            with self.subTest(architecture=architecture):
                with self.assertRaisesRegex(ValueError, "Architecture must be"):
                    self.manager.normalize_architecture(architecture)

    def test_normalize_rejects_win32_prefixes(self):
        with self.assertRaisesRegex(ValueError, "64-bit WoW64"):
            self.manager.normalize_architecture("win32")

    def test_create_initializes_prefix_and_metadata(self):
        def initialize(path, architecture):
            (path / "system.reg").write_text(
                "WINE REGISTRY\n", encoding="utf-8"
            )
            return subprocess.CompletedProcess(["runtime"], 0, "", "")

        self.runtime.create_prefix.side_effect = initialize

        path = self.manager.create("fresh-prefix", architecture="x86")

        self.assertTrue((path / "system.reg").is_file())

        metadata = json.loads(
            (path / ".winux-prefix.json").read_text(encoding="utf-8")
        )

        self.assertEqual(metadata["architecture"], "win64")
        metadata_file = path / ".winux-prefix.json"
        self.assertEqual(metadata_file.stat().st_mode & 0o777, 0o600)
        self.assertTrue(metadata_file.read_bytes().endswith(b"\n"))
        self.runtime.create_prefix.assert_called_once_with(path, "win64")

    def test_create_refuses_existing_metadata_symlink(self):
        target = self.home / "outside-prefix-metadata.json"
        target.write_text("do not overwrite", encoding="utf-8")

        def initialize(path, architecture):
            (path / "system.reg").write_text(
                "WINE REGISTRY\\n", encoding="utf-8"
            )
            (path / ".winux-prefix.json").symlink_to(target)
            return subprocess.CompletedProcess(["runtime"], 0, "", "")

        self.runtime.create_prefix.side_effect = initialize

        with self.assertRaises(FileExistsError):
            self.manager.create("metadata-link-prefix")

        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "do not overwrite",
        )
        self.assertFalse(
            (self.manager.base_dir / "metadata-link-prefix").exists()
        )

    def test_create_rejects_unavailable_runtime(self):
        self.runtime.is_available.return_value = False

        with self.assertRaisesRegex(RuntimeError, "Runtime is not available"):
            self.manager.create("unavailable-prefix")

        self.assertFalse(
            (self.manager.base_dir / "unavailable-prefix").exists()
        )

    def test_create_removes_partial_prefix_after_failure(self):
        def fail_initialization(path, architecture):
            (path / "partial").touch()
            return subprocess.CompletedProcess(
                ["runtime"], 1, "", "runtime failed"
            )

        self.runtime.create_prefix.side_effect = fail_initialization

        with self.assertRaisesRegex(RuntimeError, "runtime failed"):
            self.manager.create("broken-prefix")

        self.assertFalse(
            (self.manager.base_dir / "broken-prefix").exists()
        )

    def test_list_ignores_invalid_and_symlink_entries(self):
        self.make_prefix("valid")
        invalid = self.manager.base_dir / "invalid"
        invalid.mkdir()

        (self.manager.base_dir / "link").symlink_to(
            self.manager.base_dir / "valid",
            target_is_directory=True,
        )

        self.assertEqual(self.manager.list(), ["valid"])

    def test_prefix_uses_its_own_runtime(self):
        runtime_b = Mock()
        runtime_b.name = "runtime-b"
        runtime_b.validate_prefix.return_value = True

        def get_runtime(name):
            return {
                "test-runtime": self.runtime,
                "runtime-b": runtime_b,
            }[name]

        self.runtime_manager.get.side_effect = get_runtime

        path = self.make_prefix("runtime-b-prefix")
        (path / ".winux-prefix.json").write_text(
            json.dumps({
                "name": "runtime-b-prefix",
                "architecture": "win64",
                "runtime": "runtime-b",
                "format_version": 1,
            }),
            encoding="utf-8",
        )

        self.assertEqual(
            self.manager.get_runtime("runtime-b-prefix"),
            runtime_b,
        )
        runtime_b.validate_prefix.assert_called()

    def test_list_validates_each_prefix_with_its_own_runtime(self):
        runtime_b = Mock()
        runtime_b.name = "runtime-b"
        runtime_b.validate_prefix.return_value = True

        def get_runtime(name):
            return {
                "test-runtime": self.runtime,
                "runtime-b": runtime_b,
            }[name]

        self.runtime_manager.get.side_effect = get_runtime

        self.make_prefix("default-prefix")
        other = self.make_prefix("other-prefix")
        (other / ".winux-prefix.json").write_text(
            json.dumps({
                "name": "other-prefix",
                "architecture": "win64",
                "runtime": "runtime-b",
                "format_version": 1,
            }),
            encoding="utf-8",
        )

        self.assertEqual(
            self.manager.list(),
            ["default-prefix", "other-prefix"],
        )
        runtime_b.validate_prefix.assert_called_once_with(other)

    def test_unknown_prefix_runtime_is_rejected(self):
        path = self.make_prefix("unknown-runtime")
        (path / ".winux-prefix.json").write_text(
            json.dumps({
                "name": "unknown-runtime",
                "architecture": "win64",
                "runtime": "missing-runtime",
                "format_version": 1,
            }),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            self.manager.get_runtime("unknown-runtime")

    def test_legacy_prefix_uses_default_runtime(self):
        self.make_prefix("legacy-prefix")

        self.assertEqual(
            self.manager.get_runtime("legacy-prefix"),
            self.runtime,
        )
        self.runtime_manager.get.assert_called_with("test-runtime")

    def test_get_architecture_reads_metadata_and_supports_legacy_prefixes(self):
        self.make_prefix("modern", "win64")
        self.make_prefix("legacy")

        self.assertEqual(self.manager.get_architecture("modern"), "win64")
        self.assertEqual(self.manager.get_architecture("legacy"), "win64")

    def test_get_architecture_rejects_win32_metadata(self):
        self.make_prefix("invalid-architecture", "win32")

        with self.assertRaisesRegex(ValueError, "Invalid prefix architecture"):
            self.manager.get_architecture("invalid-architecture")

    def test_older_metadata_without_name_or_architecture_remains_compatible(self):
        path = self.make_prefix("older-metadata")
        metadata = path / ".winux-prefix.json"
        metadata.write_text(json.dumps({"runtime": "test-runtime"}), encoding="utf-8")

        self.assertEqual(self.manager.get_architecture("older-metadata"), "win64")
        self.assertEqual(self.manager.get_path("older-metadata"), path)

    def test_metadata_name_must_match_prefix_directory(self):
        path = self.make_prefix("metadata-name", "win64")
        metadata = path / ".winux-prefix.json"
        data = json.loads(metadata.read_text(encoding="utf-8"))
        data["name"] = "different-prefix"
        metadata.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "does not match"):
            self.manager.get_path("metadata-name")

    def test_metadata_rejects_unsupported_architecture(self):
        path = self.make_prefix("metadata-architecture", "win64")
        metadata = path / ".winux-prefix.json"
        data = json.loads(metadata.read_text(encoding="utf-8"))
        data["architecture"] = "win32"
        metadata.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "architecture"):
            self.manager.get_path("metadata-architecture")

    def test_metadata_rejects_unsupported_format_version(self):
        path = self.make_prefix("metadata-version", "win64")
        metadata = path / ".winux-prefix.json"
        data = json.loads(metadata.read_text(encoding="utf-8"))
        data["format_version"] = 2
        metadata.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "format version"):
            self.manager.get_path("metadata-version")

    def test_dangling_metadata_symlink_is_not_treated_as_legacy(self):
        path = self.make_prefix("dangling-metadata")
        (path / ".winux-prefix.json").symlink_to(path / "missing.json")

        with self.assertRaisesRegex(ValueError, "metadata"):
            self.manager.get_path("dangling-metadata")

    def test_delete_requires_explicit_confirmation(self):
        self.make_prefix("to-delete")

        with self.assertRaises(PermissionError):
            self.manager.delete("to-delete")

        self.assertTrue((self.manager.base_dir / "to-delete").exists())
        self.assertTrue(self.manager.delete("to-delete", confirm=True))
        self.assertFalse((self.manager.base_dir / "to-delete").exists())


if __name__ == "__main__":
    unittest.main()
