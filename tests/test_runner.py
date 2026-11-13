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
        self.home_patcher = patch.object(Path, "home", return_value=self.home)
        self.home_patcher.start()

        self.runner = ApplicationRunner()
        self.prefix_path = self.home / ".local/share/winux/prefixes/test-prefix"
        self.drive_c = self.prefix_path / "drive_c"
        self.drive_c.mkdir(parents=True)

        self.executable = self.drive_c / "Program Files" / "Example" / "app.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"MZ")

        self.runner.prefix_manager = Mock()
        self.runner.prefix_manager.get_path.return_value = self.prefix_path

        self.runner.application_manager = Mock()
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Example App",
            "executable_path": str(self.executable),
        }

    def tearDown(self):
        self.home_patcher.stop()
        self.temp_dir.cleanup()

    def test_run_launches_application_with_correct_prefix(self):
        with patch("winux.core.runner.shutil.which", return_value="/usr/bin/wine"), patch(
            "winux.core.runner.subprocess.Popen",
            return_value=SimpleNamespace(pid=4321),
        ) as popen:
            result = self.runner.run("test-prefix", "Example")

        self.assertEqual(result["pid"], 4321)
        self.assertEqual(result["application"], "Example App")
        self.assertEqual(result["executable"], str(self.executable))
        self.assertTrue(Path(result["log"]).is_file())

        command, = popen.call_args.args
        self.assertEqual(command, ["/usr/bin/wine", str(self.executable)])
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["cwd"], str(self.executable.parent))
        self.assertEqual(kwargs["env"]["WINEPREFIX"], str(self.prefix_path))
        self.assertIsNone(kwargs["stdin"])
        self.assertTrue(kwargs["start_new_session"])

    def test_run_fails_when_wine_is_missing(self):
        with patch("winux.core.runner.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Wine executable not found"):
                self.runner.run("test-prefix", "Example")

    def test_run_fails_when_application_has_no_executable_path(self):
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Example App",
            "executable_path": None,
        }
        with patch("winux.core.runner.shutil.which", return_value="/usr/bin/wine"):
            with self.assertRaisesRegex(FileNotFoundError, "path was not found"):
                self.runner.run("test-prefix", "Example")

    def test_run_rejects_executable_outside_prefix(self):
        outside = self.home / "outside.exe"
        outside.write_bytes(b"MZ")
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Outside App",
            "executable_path": str(outside),
        }

        with patch("winux.core.runner.shutil.which", return_value="/usr/bin/wine"):
            with self.assertRaisesRegex(ValueError, "outside the Wine prefix"):
                self.runner.run("test-prefix", "Outside")

    def test_run_fails_when_executable_does_not_exist(self):
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Missing App",
            "executable_path": str(self.drive_c / "missing.exe"),
        }

        with patch("winux.core.runner.shutil.which", return_value="/usr/bin/wine"):
            with self.assertRaises(FileNotFoundError):
                self.runner.run("test-prefix", "Missing")


if __name__ == "__main__":
    unittest.main()
