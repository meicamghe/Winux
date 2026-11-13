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


if __name__ == "__main__":
    unittest.main()
