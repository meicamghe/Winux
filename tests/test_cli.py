import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
