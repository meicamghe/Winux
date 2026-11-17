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
            with patch("winux.core.applications.ApplicationManager.info", return_value={"DisplayName": "Example App"}):
                with patch("builtins.input", return_value="y"):
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
            with patch("winux.core.applications.ApplicationManager.info", return_value={"DisplayName": "Example App"}):
                with patch("builtins.input", return_value="y"):
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


    @patch(
        "winux.core.applications.ApplicationManager.list",
        return_value=[{
            "DisplayName": "Example App",
            "executable_path": "/prefix/drive_c/Program Files/Example/app.exe",
            "executable_status": "ready",
        }],
    )
    def test_app_list_distinguishes_executable_discovery_from_execution_test(self, list_apps):
        with patch.object(
            sys,
            "argv",
            ["winux", "app", "list", "--prefix", "test-prefix"],
        ):
            with patch("builtins.print") as output:
                main()

        rendered = str(output.call_args_list)
        self.assertIn("Executable discovery: ready", rendered)
        self.assertIn("Execution test: NOT TESTED", rendered)
        self.assertNotIn("Launch status: ready", rendered)

    @patch(
        "winux.core.applications.ApplicationManager.info",
        return_value={
            "DisplayName": "Example App",
            "executable_path": "/prefix/drive_c/Program Files/Example/app.exe",
            "executable_status": "ready",
        },
    )
    def test_app_info_does_not_present_discovery_as_a_launch_test(self, get_app):
        with patch.object(
            sys,
            "argv",
            ["winux", "app", "info", "--prefix", "test-prefix", "Example"],
        ):
            with patch("builtins.print") as output:
                main()

        rendered = str(output.call_args_list)
        self.assertIn("Executable discovery: ready", rendered)
        self.assertIn("Execution test:      NOT TESTED", rendered)
        self.assertNotIn("Launch status:    ready", rendered)


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


class PrefixRuntimeCliTests(unittest.TestCase):
    @patch("winux.core.prefix.PrefixManager")
    def test_prefix_create_displays_selected_runtime(self, manager_class):
        manager = manager_class.return_value
        manager.create.return_value = Path("/tmp/winux/prefixes/office")
        manager.get_architecture.return_value = "win64"
        manager.get_runtime.return_value.name = "wine-staging"

        with patch.object(
            sys,
            "argv",
            ["winux", "prefix", "create", "office", "--runtime", "wine-staging"],
        ):
            with patch("builtins.print") as output:
                main()

        manager.create.assert_called_once_with(
            "office", architecture="x64", runtime_name="wine-staging"
        )
        self.assertIn("wine-staging", str(output.call_args_list))

    @patch("winux.core.prefix.PrefixManager")
    def test_prefix_info_displays_bound_runtime(self, manager_class):
        manager = manager_class.return_value
        manager.get_path.return_value = Path("/tmp/winux/prefixes/office")
        manager.get_architecture.return_value = "win64"
        manager.get_runtime.return_value.name = "wine-stable"

        with patch.object(
            sys, "argv", ["winux", "prefix", "info", "office"]
        ):
            with patch("builtins.print") as output:
                main()

        manager.get_runtime.assert_called_once_with("office")
        self.assertIn("wine-stable", str(output.call_args_list))


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
                    installer_args=[],
                )




    @patch("winux.core.installer.Installer")
    def test_install_command_forwards_repeated_installer_arguments(self, installer_class):
        installer = installer_class.return_value
        installer.install.return_value = {
            "process_status": "SUCCESS",
            "verification_status": "PENDING",
            "verification_details": "not requested",
            "install_id": "test-install",
            "log": "/tmp/test.log",
        }

        with patch.object(
            sys,
            "argv",
            [
                "winux", "install", "setup.exe",
                "--prefix", "test-prefix",
                "--installer-arg", "/S",
                "--installer-arg", "/D=C:\\Apps\\Example",
            ],
        ):
            with patch("builtins.print"):
                main()

        installer.install.assert_called_once_with(
            installer_file="setup.exe",
            prefix_name="test-prefix",
            timeout=3600,
            verification_profile=None,
            installer_args=["/S", "/D=C:\\Apps\\Example"],
        )

    @patch("winux.core.installer.Installer")
    def test_batch_install_rejects_cli_installer_arguments(self, installer_class):
        with patch.object(
            sys,
            "argv",
            [
                "winux", "install",
                "--manifest", "batch.json",
                "--prefix", "test-prefix",
                "--installer-arg", "/S",
            ],
        ):
            with patch("builtins.print"):
                with self.assertRaises(SystemExit) as raised:
                    main()

        self.assertEqual(raised.exception.code, 1)
        installer_class.return_value.install_batch.assert_not_called()


class ApplicationRunCliTests(unittest.TestCase):
    @patch("winux.core.runner.ApplicationRunner.run")
    def test_run_command_forwards_arguments_after_separator(self, run):
        run.return_value = {
            "application": "Example App",
            "pid": 1234,
            "process_id": "process-id",
            "executable": "/prefix/app.exe",
            "log": "/tmp/app.log",
        }

        with patch.object(
            sys,
            "argv",
            [
                "winux", "app", "run",
                "--prefix", "test-prefix",
                "Example",
                "--",
                "document with spaces.docx",
                "--readonly",
            ],
        ):
            with patch("builtins.print"):
                main()

        run.assert_called_once_with(
            "test-prefix",
            "Example",
            args=["document with spaces.docx", "--readonly"],
        )


if __name__ == "__main__":
    unittest.main()


class ServiceCliTests(unittest.TestCase):

    SERVICE_ID = "a" * 32

    def run_cli(self, arguments):
        from unittest.mock import patch

        with patch(
            "winux.core.services.ServiceManager"
        ) as manager_class:
            manager = manager_class.return_value

            with patch.object(sys, "argv", ["winux", *arguments]):
                with patch("builtins.print") as output:
                    main()

            return manager, output

    def test_service_create(self):
        from unittest.mock import patch

        record = {
            "id": self.SERVICE_ID,
            "name": "Example",
            "prefix": "test-prefix",
            "application": "Example App",
            "restart": "on-failure",
        }

        with patch(
            "winux.core.services.ServiceManager"
        ) as manager_class:
            manager = manager_class.return_value
            manager.create.return_value = record

            with patch.object(
                sys,
                "argv",
                [
                    "winux", "service", "create",
                    "--name", "Example",
                    "--prefix", "test-prefix",
                    "--application", "example-id",
                ],
            ):
                with patch("builtins.print") as output:
                    main()

        manager.create.assert_called_once_with(
            name="Example",
            prefix_name="test-prefix",
            application_id="example-id",
            restart="on-failure",
        )
        self.assertIn(
            "not started or enabled",
            str(output.call_args_list),
        )

    def test_service_list(self):
        from unittest.mock import patch

        record = {
            "id": self.SERVICE_ID,
            "name": "Example",
            "application": "Example App",
            "prefix": "test-prefix",
            "status": {
                "active_state": "active",
                "unit_file_state": "enabled",
            },
        }

        with patch(
            "winux.core.services.ServiceManager"
        ) as manager_class:
            manager = manager_class.return_value
            manager.list.return_value = [record]

            with patch.object(
                sys, "argv", ["winux", "service", "list"]
            ):
                with patch("builtins.print") as output:
                    main()

        manager.list.assert_called_once_with()
        self.assertIn("Example", str(output.call_args_list))
        self.assertIn("active", str(output.call_args_list))

    def test_service_status(self):
        from unittest.mock import patch

        record = {
            "id": self.SERVICE_ID,
            "name": "Example",
            "application": "Example App",
            "prefix": "test-prefix",
            "status": {
                "load_state": "loaded",
                "active_state": "inactive",
                "sub_state": "dead",
                "unit_file_state": "disabled",
            },
        }

        with patch(
            "winux.core.services.ServiceManager"
        ) as manager_class:
            manager = manager_class.return_value
            manager.get.return_value = record

            with patch.object(
                sys,
                "argv",
                ["winux", "service", "status", self.SERVICE_ID],
            ):
                with patch("builtins.print") as output:
                    main()

        manager.get.assert_called_once_with(self.SERVICE_ID)
        self.assertIn("inactive", str(output.call_args_list))

    def test_service_lifecycle_commands(self):
        from unittest.mock import patch

        record = {
            "id": self.SERVICE_ID,
            "name": "Example",
            "status": {
                "active_state": "inactive",
                "unit_file_state": "disabled",
            },
        }

        actions = (
            "start", "stop", "restart", "enable", "disable", "delete"
        )

        for action in actions:
            with self.subTest(action=action):
                with patch(
                    "winux.core.services.ServiceManager"
                ) as manager_class:
                    manager = manager_class.return_value

                    if action == "delete":
                        manager.delete.return_value = record
                    else:
                        getattr(manager, action).return_value = record

                    with patch.object(
                        sys,
                        "argv",
                        [
                            "winux", "service", action,
                            self.SERVICE_ID,
                        ],
                    ):
                        with patch("builtins.print") as output:
                            main()

                    getattr(manager, action).assert_called_once_with(
                        self.SERVICE_ID
                    )

                    if action == "disable":
                        self.assertIn(
                            "does not stop",
                            str(output.call_args_list),
                        )


class DoctorCliTests(unittest.TestCase):
    def test_doctor_returns_nonzero_when_diagnostics_fail(self):
        with patch.object(sys, "argv", ["winux", "doctor"]):
            with patch("winux.platform.runtime.check_runtime", return_value=False):
                with self.assertRaises(SystemExit) as raised:
                    main()
        self.assertEqual(raised.exception.code, 1)

    def test_doctor_returns_success_when_diagnostics_pass(self):
        with patch.object(sys, "argv", ["winux", "doctor"]):
            with patch("winux.platform.runtime.check_runtime", return_value=True) as check:
                main()
        check.assert_called_once_with()



class ApplicationUninstallCliTests(unittest.TestCase):
    def setUp(self):
        self.application = {"DisplayName": "Example App"}

    @patch("winux.core.applications.ApplicationManager")
    def test_uninstall_requires_confirmation_by_default(self, manager_class):
        manager = manager_class.return_value
        manager.info.return_value = self.application

        with patch.object(
            sys,
            "argv",
            [
                "winux", "app", "uninstall",
                "--prefix", "test-prefix",
                "Example",
            ],
        ):
            with patch("builtins.input", return_value="n") as prompt:
                with patch("builtins.print"):
                    main()

        prompt.assert_called_once()
        manager.info.assert_called_once_with("test-prefix", "Example")
        manager.uninstall.assert_not_called()

    @patch("winux.core.applications.ApplicationManager")
    def test_uninstall_yes_skips_confirmation(self, manager_class):
        manager = manager_class.return_value
        manager.info.return_value = self.application
        manager.uninstall.return_value = {
            "success": True,
            "application": "Example App",
            "prefix": "test-prefix",
        }

        with patch.object(
            sys,
            "argv",
            [
                "winux", "app", "uninstall",
                "--prefix", "test-prefix",
                "Example",
                "--yes",
            ],
        ):
            with patch("builtins.input") as prompt:
                with patch("builtins.print"):
                    main()

        prompt.assert_not_called()
        manager.uninstall.assert_called_once_with(
            "test-prefix", "Example", timeout=300
        )

    @patch("winux.core.applications.ApplicationManager")
    def test_uninstall_confirmation_accepts_uppercase_yes(self, manager_class):
        manager = manager_class.return_value
        manager.info.return_value = self.application
        manager.uninstall.return_value = {
            "success": True,
            "application": "Example App",
            "prefix": "test-prefix",
        }

        with patch.object(
            sys,
            "argv",
            [
                "winux", "app", "uninstall",
                "--prefix", "test-prefix",
                "Example",
            ],
        ):
            with patch("builtins.input", return_value="Y"):
                with patch("builtins.print"):
                    main()

        manager.uninstall.assert_called_once_with(
            "test-prefix", "Example", timeout=300
        )


class ApplicationRegistryViewCliTests(unittest.TestCase):
    @patch("winux.core.applications.ApplicationManager")
    def test_app_list_displays_all_registry_ids_and_keys(self, manager_class):
        manager = manager_class.return_value
        manager.list.return_value = [{
            "DisplayName": "MSI Example",
            "registry_id": "native-id",
            "registry_ids": ["native-id", "wow-id"],
            "registry_keys": ["native-key", "wow-key"],
        }]

        with patch.object(sys, "argv", ["winux", "app", "list", "--prefix", "office"]):
            with patch("builtins.print") as output:
                main()

        rendered = str(output.call_args_list)
        self.assertIn("native-id", rendered)
        self.assertIn("wow-id", rendered)
        self.assertIn("native-key", rendered)
        self.assertIn("wow-key", rendered)

    @patch("winux.core.applications.ApplicationManager")
    def test_app_info_displays_uninstall_commands_for_each_registry_view(self, manager_class):
        manager = manager_class.return_value
        manager.info.return_value = {
            "DisplayName": "MSI Example",
            "registry_id": "native-id",
            "registry_key": "native-key",
            "registry_ids": ["native-id", "wow-id"],
            "registry_keys": ["native-key", "wow-key"],
            "uninstall_commands": [
                {"registry_id": "native-id", "quiet": None, "normal": "msiexec /I{ABC}"},
                {"registry_id": "wow-id", "quiet": "msiexec /x {ABC} /qn", "normal": None},
            ],
        }

        with patch.object(sys, "argv", ["winux", "app", "info", "--prefix", "office", "native-id"]):
            with patch("builtins.print") as output:
                main()

        rendered = str(output.call_args_list)
        self.assertIn("wow-id", rendered)
        self.assertIn("wow-key", rendered)
        self.assertIn("msiexec /x {ABC} /qn", rendered)
