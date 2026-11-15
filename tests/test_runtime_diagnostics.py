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

    def test_unavailable_runtime_fails_diagnostics(self):
        self.runtime.is_available.return_value = False
        with patch("builtins.print"):
            self.assertFalse(check_runtime(self.manager))

    def test_runtime_version_failure_fails_diagnostics(self):
        self.runtime.version.side_effect = RuntimeError("version probe failed")
        with patch("builtins.print"):
            self.assertFalse(check_runtime(self.manager))

    def test_plugin_failures_are_reported_without_failing_core_runtime(self):
        self.manager.plugin_errors.return_value = [{
            "plugin": "optional-runtime",
            "stage": "load",
            "error": "plugin unavailable",
        }]
        with patch("builtins.print") as output:
            self.assertTrue(check_runtime(self.manager))
        rendered = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("optional-runtime", rendered)


if __name__ == "__main__":
    unittest.main()
