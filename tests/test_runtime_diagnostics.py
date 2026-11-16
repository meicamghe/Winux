import subprocess
import unittest
from unittest.mock import Mock, patch

from winux.platform.runtime import check_runtime


class RuntimeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Mock()
        self.runtime.is_available.return_value = True
        self.runtime.version.return_value = "wine-10.0"
        self.manager = Mock()
        self.manager.get_default_name.return_value = "wine"
        self.manager.get.return_value = self.runtime
        self.manager.plugin_errors.return_value = []

    @patch("winux.platform.runtime.platform.machine", return_value="x86_64")
    @patch("winux.platform.runtime._command_status", return_value="/usr/bin/tool")
    def test_all_core_tools_available(self, _commands, _machine):
        with patch("builtins.print"):
            self.assertTrue(check_runtime(self.manager))

    @patch("winux.platform.runtime._command_status")
    def test_missing_required_wineboot_fails_diagnostics(self, command):
        command.side_effect = lambda name: None if name == "wineboot" else "/usr/bin/tool"
        with patch("builtins.print"):
            self.assertFalse(check_runtime(self.manager))

    @patch("winux.platform.runtime._command_status")
    def test_missing_optional_tools_are_warnings(self, command):
        command.side_effect = lambda name: None if name in {"msiexec", "wineserver", "winepath", "msiinfo", "7z"} else "/usr/bin/tool"
        with patch("builtins.print"):
            self.assertTrue(check_runtime(self.manager))

    @patch("winux.platform.runtime.subprocess.run")
    def test_systemd_user_manager_is_reported_available(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="LANG=C.UTF-8\n",
            stderr="",
        )
        with (
            patch(
                "winux.platform.runtime._command_status",
                return_value="/usr/bin/tool",
            ),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))

        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("systemd user manager: available", rendered)

    @patch(
        "winux.platform.runtime.subprocess.run",
        side_effect=subprocess.TimeoutExpired("systemctl", 5),
    )
    def test_systemd_user_manager_unavailable_is_warning(self, _run):
        with (
            patch(
                "winux.platform.runtime._command_status",
                return_value="/usr/bin/tool",
            ),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))

        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("systemd user manager: unavailable", rendered)

    def test_missing_systemctl_is_warning_not_runtime_failure(self):
        with (
            patch(
                "winux.platform.runtime._command_status",
                side_effect=lambda name: None if name == "systemctl" else "/usr/bin/tool",
            ),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))

        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("systemd user manager: systemctl is unavailable", rendered)

    def test_unavailable_runtime_fails_diagnostics(self):
        self.runtime.is_available.return_value = False
        with patch("builtins.print"):
            self.assertFalse(check_runtime(self.manager))

    def test_runtime_version_failure_fails_diagnostics(self):
        self.runtime.version.side_effect = RuntimeError("version probe failed")
        with patch("builtins.print"):
            self.assertFalse(check_runtime(self.manager))

    def test_service_backend_plugin_failures_are_reported_as_warnings(self):
        broken_backend = Mock()
        broken_backend.name = "optional-service-backend"
        broken_backend.load.side_effect = ImportError("backend unavailable")

        with (
            patch(
                "winux.platform.runtime._command_status",
                return_value="/usr/bin/tool",
            ),
            patch(
                "winux.platform.runtime.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ),
            patch(
                "winux.platform.service_backends.entry_points",
                return_value=[broken_backend],
            ),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))

        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("optional-service-backend", rendered)
        self.assertIn("backend unavailable", rendered)

    def test_plugin_failures_are_reported_without_failing_core_runtime(self):
        self.manager.plugin_errors.return_value = [{
            "plugin": "optional-runtime",
            "stage": "load",
            "error": "plugin unavailable",
        }]
        with (
            patch(
                "winux.platform.runtime._command_status",
                return_value="/usr/bin/tool",
            ),
            patch(
                "winux.platform.runtime.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                ),
            ),
            patch(
                "winux.platform.service_backends.entry_points",
                return_value=[],
            ),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))
        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("optional-runtime", rendered)


    def test_wine_10_reports_new_wow64_compatibility_warning(self):
        self.runtime.version.return_value = "wine-10.0 (Ubuntu 10.0~repack)"
        with (
            patch("winux.platform.runtime._command_status", return_value="/usr/bin/tool"),
            patch("winux.platform.runtime.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))
        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("Wine 10.0 detected", rendered)
        self.assertIn("Wine 11.0 or newer is recommended", rendered)

    def test_wine_11_does_not_report_old_wow64_warning(self):
        self.runtime.version.return_value = "wine-11.0"
        with (
            patch("winux.platform.runtime._command_status", return_value="/usr/bin/tool"),
            patch("winux.platform.runtime.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))
        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertNotIn("Wine 11.0 or newer is recommended", rendered)

    def test_unparseable_wine_version_reports_unknown_compatibility(self):
        self.runtime.version.return_value = "custom Wine build"
        with (
            patch("winux.platform.runtime._command_status", return_value="/usr/bin/tool"),
            patch("winux.platform.runtime.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))
        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("WoW64 compatibility is unknown", rendered)


    def test_wine_11_development_build_reports_build_capability_caveat(self):
        self.runtime.version.return_value = "wine-11.22"
        with (
            patch("winux.platform.runtime._command_status", return_value="/usr/bin/tool"),
            patch("winux.platform.runtime.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")),
            patch("builtins.print") as output,
        ):
            self.assertTrue(check_runtime(self.manager))
        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("does not confirm", rendered)

    def test_unrelated_numeric_version_is_not_misidentified_as_wine(self):
        from winux.platform.runtime import _wine_version_warning

        self.assertIn("unknown", _wine_version_warning("custom build 11.22"))
        self.assertIn(
            "does not confirm",
            _wine_version_warning("wine-11.22 (Staging)"),
        )


if __name__ == "__main__":
    unittest.main()
