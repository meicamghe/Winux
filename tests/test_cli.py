import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winux.__main__ import main


class ApplicationCliTests(unittest.TestCase):

    @patch(
        "winux.core.applications.ApplicationManager.uninstall",
        return_value={
            "success": True,
            "application": "Example App",
            "prefix": "test-prefix",
            "returncode": 0,
        },
    )
    def test_uninstall_command_calls_manager(self, uninstall):
        with patch.object(
            sys,
            "argv",
            [
                "winux",
                "app",
                "uninstall",
                "--prefix",
                "test-prefix",
                "Example",
            ],
        ):
            with patch("builtins.print"):
                main()

        uninstall.assert_called_once_with(
            "test-prefix",
            "Example",
            timeout=300,
        )

    @patch(
        "winux.core.applications.ApplicationManager.uninstall",
        return_value={
            "success": True,
            "application": "Example App",
            "prefix": "test-prefix",
            "returncode": 0,
        },
    )
    def test_uninstall_command_accepts_custom_timeout(self, uninstall):
        with patch.object(
            sys,
            "argv",
            [
                "winux",
                "app",
                "uninstall",
                "--prefix",
                "test-prefix",
                "--timeout",
                "120",
                "Example",
            ],
        ):
            with patch("builtins.print"):
                main()

        uninstall.assert_called_once_with(
            "test-prefix",
            "Example",
            timeout=120,
        )


    @patch(
        "winux.core.applications.ApplicationManager.export",
        return_value={
            "success": True,
            "prefix": "test-prefix",
            "format": "json",
            "path": "/tmp/apps.json",
            "count": 3,
        },
    )
    def test_export_command_uses_json_by_default(self, export):
        with patch.object(
            sys,
            "argv",
            [
                "winux",
                "app",
                "export",
                "--prefix",
                "test-prefix",
                "--output",
                "/tmp/apps.json",
            ],
        ):
            with patch("builtins.print") as print_mock:
                main()

        export.assert_called_once_with(
            "test-prefix",
            "/tmp/apps.json",
            "json",
        )
        self.assertTrue(
            any("[OK] Applications exported." in str(call)
                for call in print_mock.call_args_list)
        )

    @patch(
        "winux.core.applications.ApplicationManager.export",
        return_value={
            "success": True,
            "prefix": "test-prefix",
            "format": "csv",
            "path": "/tmp/apps.csv",
            "count": 2,
        },
    )
    def test_export_command_accepts_csv_format(self, export):
        with patch.object(
            sys,
            "argv",
            [
                "winux",
                "app",
                "export",
                "--prefix",
                "test-prefix",
                "--output",
                "/tmp/apps.csv",
                "--format",
                "csv",
            ],
        ):
            with patch("builtins.print"):
                main()

        export.assert_called_once_with(
            "test-prefix",
            "/tmp/apps.csv",
            "csv",
        )


class ProcessCliTests(unittest.TestCase):

    @patch("winux.core.processes.ProcessManager.list")
    def test_process_list(self, list_processes):
        list_processes.return_value = [{
            "id": "process-123",
            "pid": 4321,
            "application": "Example App",
            "prefix": "test-prefix",
            "runtime": "wine",
            "status": "running",
        }]

        with patch.object(
            sys, "argv", ["winux", "process", "list"]
        ):
            with patch("builtins.print") as output:
                main()

        list_processes.assert_called_once_with(include_inactive=True)
        rendered = str(output.call_args_list)
        self.assertIn("process-123", rendered)
        self.assertIn("Example App", rendered)

    @patch("winux.core.processes.ProcessManager.list", return_value=[])
    def test_process_list_running_only(self, list_processes):
        with patch.object(
            sys,
            "argv",
            ["winux", "process", "list", "--running-only"],
        ):
            with patch("builtins.print"):
                main()

        list_processes.assert_called_once_with(include_inactive=False)

    @patch(
        "winux.core.processes.ProcessManager.get",
        return_value={
            "id": "process-123",
            "pid": 4321,
            "status": "running",
            "application": "Example App",
            "prefix": "test-prefix",
            "runtime": "wine",
            "executable": "/prefix/app.exe",
            "command": "wine app.exe",
            "log": "/tmp/app.log",
            "started_at": "2026-11-14T12:00:00+00:00",
            "uid": 1000,
        },
    )
    def test_process_info(self, get_process):
        with patch.object(
            sys,
            "argv",
            ["winux", "process", "info", "process-123"],
        ):
            with patch("builtins.print") as output:
                main()

        get_process.assert_called_once_with("process-123")
        self.assertIn("Example App", str(output.call_args_list))

    @patch(
        "winux.core.processes.ProcessManager.stop",
        return_value={
            "id": "process-123",
            "pid": 4321,
            "status": "exited",
            "stopped": True,
            "forced": True,
        },
    )
    def test_process_stop(self, stop_process):
        with patch.object(
            sys,
            "argv",
            [
                "winux", "process", "stop", "process-123",
                "--timeout", "2.5", "--force",
            ],
        ):
            with patch("builtins.print") as output:
                main()

        stop_process.assert_called_once_with(
            "process-123",
            timeout=2.5,
            force=True,
        )
        self.assertIn("SIGKILL", str(output.call_args_list))

    @patch(
        "winux.core.processes.ProcessManager.cleanup",
        return_value={"removed": 3, "remaining": 1},
    )
    def test_process_cleanup(self, cleanup):
        with patch.object(
            sys, "argv", ["winux", "process", "cleanup"]
        ):
            with patch("builtins.print") as output:
                main()

        cleanup.assert_called_once_with()
        rendered = str(output.call_args_list)
        self.assertIn("3", rendered)
        self.assertIn("1", rendered)


class InstallerCliTests(unittest.TestCase):

    def test_install_command_loads_and_forwards_verification_profile(self):
        profile = {
            "checks": [{
                "type": "file",
                "path": r"Program Files\\Example\\app.exe",
            }]
        }

        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.json"
            profile_path.write_text(
                json.dumps(profile),
                encoding="utf-8",
            )

            with patch("winux.core.installer.Installer") as installer_class:
                installer = installer_class.return_value
                installer.install.return_value = {
                    "process_status": "SUCCESS",
                    "verification_status": "VERIFIED",
                    "verification_details": "file found",
                    "install_id": "test-install",
                    "log": "/tmp/test.log",
                }

                with patch.object(
                    sys,
                    "argv",
                    [
                        "winux",
                        "install",
                        "example.exe",
                        "--prefix",
                        "test-prefix",
                        "--verification-profile",
                        str(profile_path),
                    ],
                ):
                    with patch("builtins.print"):
                        main()

                installer.verification_manager.validate_profile.assert_called_once_with(
                    profile
                )
                installer.install.assert_called_once_with(
                    installer_file="example.exe",
                    prefix_name="test-prefix",
                    timeout=3600,
                    verification_profile=profile,
                )


if __name__ == "__main__":
    unittest.main()
