import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winux.core.applications import ApplicationManager
from winux.core.desktop import DesktopManager


class StartMenuInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.prefix = Path(self.temp.name) / "prefix"
        self.drive = self.prefix / "drive_c"
        self.drive.mkdir(parents=True)
        self.runtime = type("Runtime", (), {
            "is_available": lambda *_args, **_kwargs: True,
            "query_registry": lambda *_args, **_kwargs: type(
                "Result", (), {"returncode": 0, "stdout": "", "stderr": ""}
            )()
        })()
        self.manager = object.__new__(ApplicationManager)
        self.manager.runtime_manager = type("RuntimeManager", (), {
            "get": lambda *_args, **_kwargs: self.runtime
        })()
        self.manager.prefix_manager = type("PrefixManager", (), {
            "get_path": lambda *_args, **_kwargs: self.prefix,
            "get_runtime": lambda *_args, **_kwargs: self.runtime
        })()

    def tearDown(self):
        self.temp.cleanup()

    def _shortcut(self, executable):
        menu = self.drive / "ProgramData/Microsoft/Windows/Start Menu/Programs"
        menu.mkdir(parents=True, exist_ok=True)
        shortcut = menu / "Example.lnk"
        shortcut.write_bytes(b"fixture")
        return {
            "name": "Example",
            "shortcut": str(shortcut),
            "executable_path": str(executable),
            "discovery_source": "start_menu",
        }

    def test_start_menu_candidate_is_included_in_application_inventory(self):
        executable = self.drive / "Apps/Example/app.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"MZ")
        candidate = self._shortcut(executable)

        with patch.object(
            DesktopManager, "discover_start_menu_shortcuts",
            return_value={"shortcuts": [candidate], "errors": []},
        ):
            applications = self.manager.list("test-prefix")

        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]["DisplayName"], "Example")
        self.assertEqual(applications[0]["executable_status"], "ready")
        self.assertEqual(applications[0]["discovery_source"], "start_menu")
        self.assertTrue(applications[0]["registry_id"].startswith("start-menu:"))

    def test_start_menu_duplicate_does_not_duplicate_registered_application(self):
        executable = self.drive / "Apps/Example/app.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"MZ")
        candidate = self._shortcut(executable)
        records = [{
            "registry_key": r"HKEY_LOCAL_MACHINE\\Software\\App\\Example",
            "registry_id": "Example",
            "DisplayName": "Registered Example",
            "DisplayIcon": r"C:\\Apps\\Example\\app.exe",
        }]

        with patch.object(self.manager, "_query_registry", return_value=records), patch.object(
            DesktopManager, "discover_start_menu_shortcuts",
            return_value={"shortcuts": [candidate], "errors": []},
        ):
            applications = self.manager.list("test-prefix")

        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]["registry_id"], "Example")

    def test_removed_shortcut_is_ignored_without_failing_inventory(self):
        executable = self.drive / "Apps/Example/app.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"MZ")
        candidate = self._shortcut(executable)
        Path(candidate["shortcut"]).unlink()

        with patch.object(
            DesktopManager, "discover_start_menu_shortcuts",
            return_value={"shortcuts": [candidate], "errors": []},
        ):
            applications = self.manager.list("test-prefix")

        self.assertEqual(applications, [])

    def test_start_menu_candidate_outside_prefix_is_rejected(self):
        outside = Path(self.temp.name) / "outside.exe"
        outside.write_bytes(b"MZ")
        candidate = self._shortcut(outside)

        with patch.object(
            DesktopManager, "discover_start_menu_shortcuts",
            return_value={"shortcuts": [candidate], "errors": []},
        ):
            applications = self.manager.list("test-prefix")

        self.assertEqual(applications, [])


if __name__ == "__main__":
    unittest.main()
