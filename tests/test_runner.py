import tempfile
from datetime import datetime
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

        self.process_manager = Mock()
        self.process_manager.register.return_value = {
            "id": "test-process-id",
            "status": "running",
        }

        self.runner = ApplicationRunner(
            runtime_manager=self.runtime_manager,
            process_manager=self.process_manager,
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

    def test_constructor_preserves_falsey_injected_managers(self):
        class FalseyMock(Mock):
            def __bool__(self):
                return False

        runtime_manager = FalseyMock()
        process_manager = FalseyMock()

        runner = ApplicationRunner(
            runtime_manager=runtime_manager,
            process_manager=process_manager,
        )

        self.assertIs(runner.runtime_manager, runtime_manager)
        self.assertIs(runner.process_manager, process_manager)
        self.assertIs(runner.prefix_manager.runtime_manager, runtime_manager)

    def test_run_foreground_waits_for_application_exit(self):
        process = Mock()
        process.wait.return_value = 23
        self.runtime.run.return_value = process

        result = self.runner.run_foreground(
            "test-prefix",
            "Example",
        )

        self.assertEqual(result, 23)
        self.runtime.run.assert_called_once_with(
            self.prefix_path,
            self.executable,
            cwd=str(self.executable.parent),
        )
        process.wait.assert_called_once_with()
        self.process_manager.register.assert_not_called()

    def test_run_foreground_rejects_unavailable_runtime(self):
        self.runtime.is_available.return_value = False

        with self.assertRaisesRegex(RuntimeError, "not available"):
            self.runner.run_foreground("test-prefix", "Example")

        self.runtime.run.assert_not_called()

    def test_run_foreground_rejects_missing_executable(self):
        self.runner.application_manager.info.return_value = {
            "DisplayName": "Missing App",
            "executable_path": str(self.drive_c / "missing.exe"),
        }

        with self.assertRaises(FileNotFoundError):
            self.runner.run_foreground("test-prefix", "Missing")

        self.runtime.run.assert_not_called()

    def test_run_foreground_rejects_executable_outside_prefix(self):
        outside = self.home / "outside.exe"
        outside.write_bytes(b"MZ")

        self.runner.application_manager.info.return_value = {
            "DisplayName": "Outside App",
            "executable_path": str(outside),
        }

        with self.assertRaisesRegex(ValueError, "outside the runtime prefix"):
            self.runner.run_foreground("test-prefix", "Outside")

        self.runtime.run.assert_not_called()

    def test_constructor_rejects_symlinked_log_directory(self):
        log_parent = self.home / ".local/share/winux/logs"
        log_parent.mkdir(parents=True, exist_ok=True)
        target = self.home / "outside-logs"
        target.mkdir()
        self.runner.log_dir.rmdir()
        (log_parent / "app-runs").symlink_to(
            target,
            target_is_directory=True,
        )

        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            ApplicationRunner(
                runtime_manager=self.runtime_manager,
                process_manager=self.process_manager,
            )

    def test_run_does_not_follow_existing_log_symlink(self):
        fixed_time = datetime(2026, 11, 15, 12, 0, 0)
        log_file = self.runner.log_dir / "test-prefix-20261115-120000-000000.log"
        target = self.home / "outside.log"
        target.write_text("do not overwrite", encoding="utf-8")
        log_file.symlink_to(target)

        with patch("winux.core.runner.datetime") as datetime_mock:
            datetime_mock.now.return_value = fixed_time
            with self.assertRaises(FileExistsError):
                self.runner.run("test-prefix", "Example")

        self.assertEqual(target.read_text(encoding="utf-8"), "do not overwrite")
        self.runtime.run.assert_not_called()

    def test_run_launches_application_with_correct_runtime(self):
        result = self.runner.run("test-prefix", "Example")

        self.assertEqual(result["pid"], 4321)
        self.assertEqual(result["process_id"], "test-process-id")
        self.assertEqual(result["application"], "Example App")
        self.assertEqual(result["executable"], str(self.executable))
        self.assertTrue(Path(result["log"]).is_file())
        self.assertEqual(Path(result["log"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.runner.log_dir.stat().st_mode & 0o777, 0o700)

        self.runtime.run.assert_called_once()
        args, kwargs = self.runtime.run.call_args

        self.assertEqual(args, (self.prefix_path, self.executable))
        self.assertEqual(kwargs["cwd"], str(self.executable.parent))
        self.assertEqual(kwargs["stdin"], -3)
        self.assertEqual(kwargs["stderr"], -2)
        self.assertTrue(kwargs["start_new_session"])

        self.process_manager.register.assert_called_once_with(
            pid=4321,
            application="Example App",
            prefix="test-prefix",
            runtime="test-runtime",
            executable=str(self.executable),
            log=result["log"],
        )

    def test_run_returns_result_when_process_registration_fails(self):
        self.process_manager.register.side_effect = OSError(
            "state storage unavailable"
        )

        result = self.runner.run("test-prefix", "Example")

        self.assertEqual(result["pid"], 4321)
        self.assertIsNone(result["process_id"])
        self.assertEqual(
            result["process_registration_error"],
            "state storage unavailable",
        )
        self.runtime.run.assert_called_once()

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
