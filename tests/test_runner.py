import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from winux.core.runner import ApplicationRunner


class ApplicationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)

        self.home_patcher = patch.object(
            Path, "home", return_value=self.home
        )
        self.home_patcher.start()

        self.runtime = Mock()
        self.runtime.name = "test-runtime"
        self.runtime.is_available.return_value = True
        self.runtime.run.return_value = SimpleNamespace(pid=4321)

        self.runtime_manager = Mock()
        self.runtime_manager.get.return_value = self.runtime

        self.runner = ApplicationRunner(
            runtime_manager=self.runtime_manager
        )

        self.prefix_path = (
            self.home / ".local/share/winux/prefixes/test-prefix"
        )
        self.drive_c = self.prefix_path / "drive_c"
        self.drive_c.mkdir(parents=True)

        self.executable = (
            self.drive_c / "Program Files" / "Example" / "app.exe"
        )
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"MZ")

        self.runner.prefix_manager = Mock()
        self.runner.prefix_manager.get_path.return_value = self.prefix_path
        self.runner.prefix_manager.get_runtime.return_value = self.runtime

        self.runner.application_manager = Mock()
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Example App",
            "executable_path": str(self.executable),
        }

    def tearDown(self):
        self.home_patcher.stop()
        self.temp_dir.cleanup()

    def test_run_launches_application_with_correct_runtime(self):
        result = self.runner.run("test-prefix", "Example")

        self.assertEqual(result["pid"], 4321)
        self.assertEqual(result["application"], "Example App")
        self.assertEqual(result["executable"], str(self.executable))
        self.assertTrue(Path(result["log"]).is_file())

        self.runtime.run.assert_called_once()
        args, kwargs = self.runtime.run.call_args

        self.assertEqual(args, (self.prefix_path, self.executable))
        self.assertEqual(kwargs["cwd"], str(self.executable.parent))
        self.assertEqual(kwargs["stdin"], -3)
        self.assertEqual(kwargs["stderr"], -2)
        self.assertTrue(kwargs["start_new_session"])

    def test_run_fails_when_runtime_is_unavailable(self):
        self.runtime.is_available.return_value = False

        with self.assertRaisesRegex(
            RuntimeError, "Runtime is not available: test-runtime"
        ):
            self.runner.run("test-prefix", "Example")

        self.runtime.run.assert_not_called()

    def test_run_fails_when_application_has_no_executable_path(self):
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Example App",
            "executable_path": None,
        }

        with self.assertRaisesRegex(
            FileNotFoundError, "path was not found"
        ):
            self.runner.run("test-prefix", "Example")

        self.runtime.run.assert_not_called()

    def test_run_rejects_executable_outside_prefix(self):
        outside = self.home / "outside.exe"
        outside.write_bytes(b"MZ")

        self.runner.application_manager.info.return_value = {
            "DisplayName": "Outside App",
            "executable_path": str(outside),
        }

        with self.assertRaisesRegex(
            ValueError, "outside the runtime prefix"
        ):
            self.runner.run("test-prefix", "Outside")

        self.runtime.run.assert_not_called()

    def test_run_fails_when_executable_does_not_exist(self):
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Missing App",
            "executable_path": str(self.drive_c / "missing.exe"),
        }

        with self.assertRaises(FileNotFoundError):
            self.runner.run("test-prefix", "Missing")

        self.runtime.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
